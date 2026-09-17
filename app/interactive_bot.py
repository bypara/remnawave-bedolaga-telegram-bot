"""Parallel Telegram transport; primary retains all business workers/API."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import structlog
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.bot_factory import create_bot
from app.config import settings
from app.database.database import engine
from app.migration_bot import RelaySettingsLoader, wait_for_shutdown
from app.runtime_roles import admin_handlers_enabled, interactive_allowed_ids
from app.services.interactive_consumer_lease import InteractiveConsumerLease
from app.utils.cache import cache


logger = structlog.get_logger(__name__)
PRIVATE_MESSAGE = 'Этот бот пока доступен только для тестирования. Продолжайте пользоваться основным ботом.'
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parent.parent / 'alembic.ini'


def validate_interactive_config() -> frozenset[int] | None:
    if settings.BOT_PROCESS_ROLE != 'interactive':
        raise ValueError('Для этого entrypoint требуется BOT_PROCESS_ROLE=interactive')
    if settings.BOT_PRIMARY_ID <= 0:
        raise ValueError('Задайте BOT_PRIMARY_ID — числовой ID основного бота')
    if not settings.BOT_USERNAME or not settings.BOT_USERNAME.strip().lstrip('@'):
        raise ValueError('Задайте BOT_USERNAME интерактивного бота')
    if not settings.get_database_url().startswith('postgresql'):
        raise ValueError('Параллельный бот требует общую PostgreSQL БД, не отдельный SQLite')
    if settings.get_bot_run_mode() == 'webhook':
        if not settings.get_telegram_webhook_url() or not settings.WEBHOOK_SECRET_TOKEN:
            raise ValueError('Для отдельного Telegram webhook нужны WEBHOOK_URL и WEBHOOK_SECRET_TOKEN')
        if settings.get_telegram_webhook_path() == '/health':
            raise ValueError('Telegram webhook не может использовать путь /health')
    return interactive_allowed_ids()


async def validate_interactive_identity(bot: Bot, expected_username: str) -> None:
    if bot.id == settings.BOT_PRIMARY_ID:
        raise ValueError('Нельзя запускать второй consumer с токеном основного бота')
    identity = await bot.me()
    if identity.id == settings.BOT_PRIMARY_ID or (identity.username or '').lower() != expected_username.lower():
        raise ValueError('Токен не соответствует ожидаемому имени отдельного интерактивного бота')
    cfg = Config(str(ALEMBIC_CONFIG_PATH))
    expected_revision = ScriptDirectory.from_config(cfg).get_current_head()
    async with engine.connect() as connection:
        revision = (await connection.execute(text('SELECT version_num FROM alembic_version'))).scalar_one()
    if revision != expected_revision:
        raise ValueError('Сначала обновите схему общей БД через primary-процесс; интерактивный бот не делает миграции')


class InteractiveSettingsLoader:
    """Read shared settings without startup hooks, freezing this bot's identity."""

    def __init__(self, username: str):
        self.reader = RelaySettingsLoader()
        self.username = username

    async def reload(self) -> None:
        await self.reader.reload()
        settings.BOT_USERNAME = self.username
        from app.services.maintenance_service import maintenance_service

        await maintenance_service.refresh_passive_status()


class InteractiveAccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_ids: frozenset[int] | None, loader: InteractiveSettingsLoader):
        self.allowed_ids = allowed_ids
        self.loader = loader
        # Serial execution also keeps one update's shared settings consistent.
        self.lock = asyncio.Lock()

    async def __call__(self, handler, event: Update, data: dict[str, Any]):
        item = event.message or event.callback_query or event.pre_checkout_query
        if item is None or not item.from_user or item.from_user.is_bot:
            return None
        chat = (
            event.message.chat
            if event.message
            else getattr(getattr(event.callback_query, 'message', None), 'chat', None)
        )
        if chat is not None and chat.type != ChatType.PRIVATE:
            return None
        # A completed payment must not disappear if the operator changed the test
        # allowlist after issuing the invoice. Existing handlers are idempotent.
        completed_payment = bool(event.message and event.message.successful_payment)
        if self.allowed_ids is not None and item.from_user.id not in self.allowed_ids and not completed_payment:
            if event.pre_checkout_query:
                await event.pre_checkout_query.answer(ok=False, error_message=PRIVATE_MESSAGE)
            elif event.callback_query:
                await event.callback_query.answer(PRIVATE_MESSAGE, show_alert=True)
            elif event.message:
                await event.message.answer(PRIVATE_MESSAGE, parse_mode=None)
            return None
        # Monitoring belongs to the primary even when admin handlers are enabled.
        if event.callback_query and event.callback_query.data in {
            'maintenance_monitoring',
            'admin_mon_start',
            'admin_mon_stop',
            'admin_mon_force_check',
        }:
            await event.callback_query.answer('Фоновый мониторинг управляется только в основном боте.', show_alert=True)
            return None
        async with self.lock:
            await self.loader.reload()
            return await handler(event, data)


async def admin_notice(callback: CallbackQuery) -> None:
    await callback.answer('Административные операции доступны в основном боте и кабинете.', show_alert=True)


def build_web_app(dp: Dispatcher, bot: Bot, *, path: str | None, secret: str | None) -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)

    async def health(request):
        return web.json_response(
            {
                'status': 'ok',
                'role': 'interactive',
                'business_workers': False,
                'private_test': not settings.BOT_INTERACTIVE_PUBLIC_ACCESS,
                'admin_enabled': admin_handlers_enabled(),
            }
        )

    app.router.add_get('/health', health)
    if path:
        if not secret or path == '/health':
            raise ValueError('Нужны отдельный защищённый webhook и путь, отличный от /health')
        SimpleRequestHandler(dp, bot, handle_in_background=False, secret_token=secret).register(app, path=path)
    return app


async def main():
    # Validate before touching Telegram transport, DB migrations or primary jobs.
    allowed_ids = validate_interactive_config()
    username = settings.BOT_USERNAME.strip().lstrip('@')
    mode = settings.get_bot_run_mode()
    url = settings.get_telegram_webhook_url()
    path = settings.get_telegram_webhook_path()
    secret = settings.WEBHOOK_SECRET_TOKEN
    host, port = settings.WEB_API_HOST, settings.WEB_API_PORT
    bot = create_bot()
    dp = None
    runner = None
    try:
        await validate_interactive_identity(bot, username)
        async with InteractiveConsumerLease(bot.id):
            try:
                loader = InteractiveSettingsLoader(username)
                await loader.reload()
                from app.bot import setup_bot

                _, dp = await setup_bot(bot=bot)
                dp.update.outer_middleware(InteractiveAccessMiddleware(allowed_ids, loader))
                if not admin_handlers_enabled():
                    dp.callback_query.register(admin_notice, F.data == 'admin_panel')
                app = build_web_app(dp, bot, path=path if mode == 'webhook' else None, secret=secret)
                runner = web.AppRunner(app)
                await runner.setup()
                await web.TCPSite(runner, host, port).start()
                logger.info(
                    'Интерактивный бот подготовлен, фоновые бизнес-задачи отсутствуют',
                    transport=mode,
                    public_access=settings.BOT_INTERACTIVE_PUBLIC_ACCESS,
                    admin_enabled=admin_handlers_enabled(),
                )
                allowed_updates = dp.resolve_used_update_types()
                if mode == 'webhook':
                    await bot.set_webhook(
                        url=url, secret_token=secret, allowed_updates=allowed_updates, drop_pending_updates=False
                    )
                    await wait_for_shutdown()
                else:
                    await bot.delete_webhook(drop_pending_updates=False)
                    await dp.start_polling(
                        bot, allowed_updates=allowed_updates, handle_as_tasks=False, close_bot_session=False
                    )
            finally:
                # Keep the consumer lease until in-flight updates have drained.
                if runner:
                    await runner.cleanup()
                if dp:
                    await dp.storage.close()
    finally:
        # Do not remove webhook / drop queued updates during a transport restart.
        await cache.disconnect()
        await bot.session.close()
        await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
