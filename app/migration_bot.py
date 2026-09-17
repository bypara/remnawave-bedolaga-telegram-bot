"""Explicit legacy-bot relay. Never imports main/setup_bot or starts business workers."""

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from sqlalchemy import select

from app.bot_factory import create_bot
from app.config import refresh_classic_period_prices, refresh_period_prices, settings
from app.database.database import AsyncSessionLocal, engine
from app.database.models import BotMigrationClaim, SystemSetting
from app.middlewares.bot_migration import BotMigrationMiddleware
from app.services.bot_migration_service import migration_target_username
from app.services.system_settings_service import BotConfigurationService


logger = structlog.get_logger(__name__)
PAUSED_MESSAGE = 'Переезд временно приостановлен. Попробуйте обратиться к боту позже.'
UNAVAILABLE_MESSAGE = 'Не удалось подготовить переход. Попробуйте ещё раз чуть позже.'
ALLOWED_UPDATES = ['message', 'callback_query', 'pre_checkout_query']


class RelaySettingsLoader:
    """Read shared settings without setters which can start backup/sync schedulers.

    Capture this process's environment defaults once. Removing an override must
    restore its original value, not leave a stale enabled mode in the relay.
    """

    def __init__(self):
        BotConfigurationService.initialize_definitions()
        self.defaults = {
            key: getattr(settings, key)
            for key in BotConfigurationService._definitions
            if not BotConfigurationService._is_env_override(key)
        }

    async def reload(self):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(SystemSetting))).scalars().all()
        values = dict(self.defaults)
        for row in rows:
            if row.key in values:
                values[row.key] = BotConfigurationService.deserialize_value(row.key, row.value)
        # Parse everything before publishing; invalid settings fail closed.
        for key, value in values.items():
            setattr(settings, key, value)
        refresh_period_prices()
        refresh_classic_period_prices()


async def validate_relay(bot: Bot):
    """Reject a disabled relay, missing schema or the target bot's token."""
    if not settings.BOT_MIGRATION_ENABLED:
        raise ValueError('Лёгкий бот запускается только при включённом режиме переезда.')
    target = migration_target_username()
    if not target:
        raise ValueError('Сначала задайте ссылку нового бота.')
    identity = await bot.me()
    if not identity.username or identity.username.lower() == target:
        raise ValueError('Для заглушки нужен токен СТАРОГО бота, а не целевого.')
    # Main service owns schema upgrades. The relay never migrates the shared DB.
    async with AsyncSessionLocal() as db:
        await db.execute(select(BotMigrationClaim.user_id).limit(0))


async def _notice(event: TelegramObject, bot: Bot, text: str):
    if isinstance(event, CallbackQuery):
        if event.message and event.message.chat.type != ChatType.PRIVATE:
            return
        try:
            await event.answer()
        except Exception:
            # Historical callbacks can already be expired.
            pass
        await bot.send_message(event.from_user.id, text, parse_mode=None)
    elif isinstance(event, Message) and event.chat.type == ChatType.PRIVATE:
        await event.answer(text, parse_mode=None)


class RelaySettingsMiddleware(BaseMiddleware):
    def __init__(self, loader: RelaySettingsLoader):
        self.loader = loader
        self.lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        # Keep one update's promised amount/target consistent during live edits.
        async with self.lock:
            try:
                await self.loader.reload()
            except Exception as error:
                logger.error('Не удалось прочитать настройки заглушки', error_type=type(error).__name__)
                query = event.pre_checkout_query
                if query:
                    await query.answer(ok=False, error_message=UNAVAILABLE_MESSAGE)
                elif event.message and event.message.successful_payment:
                    # Never acknowledge an already paid webhook without processing it.
                    raise
                else:
                    await _notice(event.message or event.callback_query, data['bot'], UNAVAILABLE_MESSAGE)
                return None
            return await handler(event, data)


async def legacy_successful_payment(message: Message, state):
    # Lazy import: the ordinary relay path does not even import payment services.
    from app.handlers.stars_payments import handle_successful_payment

    async with AsyncSessionLocal() as db:
        await handle_successful_payment(message, db=db, state=state)


async def legacy_pre_checkout(query):
    from app.handlers.stars_payments import handle_pre_checkout_query

    await handle_pre_checkout_query(query)


async def unsupported_pre_checkout(query):
    await query.answer(ok=False, error_message='Оплата этого счёта недоступна. Обратитесь в поддержку.')


async def relay_fallback(event: TelegramObject, bot: Bot):
    # Disabling the flag must NEVER fall through to full bot functionality.
    await _notice(event, bot, PAUSED_MESSAGE)


def build_dispatcher(loader: RelaySettingsLoader) -> Dispatcher:
    # Separate ephemeral FSM: no collisions with the full bot's Redis state.
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(RelaySettingsMiddleware(loader))
    migration = BotMigrationMiddleware(relay_only=True)
    dp.message.outer_middleware(migration)
    dp.callback_query.outer_middleware(migration)
    # Only completion of existing Stars invoices, never purchase/menu handlers.
    dp.message.register(legacy_successful_payment, F.successful_payment)
    dp.pre_checkout_query.register(legacy_pre_checkout, F.currency == 'XTR')
    dp.pre_checkout_query.register(unsupported_pre_checkout)
    dp.message.register(relay_fallback)
    dp.callback_query.register(relay_fallback)
    return dp


def build_web_app(dp: Dispatcher, bot: Bot, *, path: str | None = None, secret: str | None = None) -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)

    async def health(request):
        return web.json_response({'status': 'ok', 'role': 'migration-relay', 'background_workers': False})

    app.router.add_get('/health', health)
    if path:
        if not secret:
            raise ValueError('Для webhook старого бота требуется отдельный WEBHOOK_SECRET_TOKEN.')
        if path == '/health':
            raise ValueError('Webhook не может использовать путь /health.')
        SimpleRequestHandler(dp, bot, handle_in_background=False, secret_token=secret).register(app, path=path)
    return app


async def wait_for_shutdown():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


async def main():
    # Transport/identity belong to this container's env, NOT shared admin settings.
    mode = settings.get_bot_run_mode()
    url = settings.get_telegram_webhook_url()
    path = settings.get_telegram_webhook_path()
    secret = settings.WEBHOOK_SECRET_TOKEN
    host, port = settings.WEB_API_HOST, settings.WEB_API_PORT
    bot = create_bot()
    dp = None
    runner = None
    try:
        loader = RelaySettingsLoader()
        await loader.reload()
        await validate_relay(bot)
        dp = build_dispatcher(loader)
        if mode == 'webhook' and not url:
            raise ValueError('Для webhook требуется WEBHOOK_URL старого бота.')
        app = build_web_app(dp, bot, path=path if mode == 'webhook' else None, secret=secret)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        logger.info('Лёгкий бот переезда запущен; бизнес-задач и кабинета нет', transport=mode)
        if mode == 'webhook':
            await bot.set_webhook(
                url=url, secret_token=secret, allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False
            )
            await wait_for_shutdown()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES, handle_as_tasks=False, close_bot_session=False)
    finally:
        # Leave webhook configured across restarts, preserving queued updates.
        if runner:
            await runner.cleanup()
        if dp:
            await dp.storage.close()
        await bot.session.close()
        await engine.dispose()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
