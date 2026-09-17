"""Intercept even unmatched messages and historical callbacks during migration."""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from app.bot_migration_config import render_migration_text, validate_migration_value
from app.config import settings
from app.database.database import AsyncSessionLocal
from app.services.bot_migration_service import extract_migration_token, issue_migration_link, migration_target_username
from app.utils.telegram_delivery import is_user_unreachable


logger = structlog.get_logger(__name__)


class BotMigrationMiddleware(BaseMiddleware):
    def __init__(self, *, relay_only: bool = False):
        self.relay_only = relay_only

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not (settings.BOT_MIGRATION_ENABLED or settings.BOT_MIGRATION_BONUS_ENABLED) or not isinstance(
            event, (Message, CallbackQuery)
        ):
            return await handler(event, data)
        user = event.from_user
        chat = event.chat if isinstance(event, Message) else event.message.chat if event.message else None
        if (
            not user
            or user.is_bot
            or (settings.is_admin(user.id) and not self.relay_only)
            or (chat and chat.type != ChatType.PRIVATE)
            or (isinstance(event, Message) and event.successful_payment)
        ):
            return await handler(event, data)

        bot = data.get('bot') or event.bot
        # Both bots may read settings from the same DB. Never stub the target bot.
        try:
            identity = await bot.me()
        except Exception as error:
            logger.warning('Не удалось проверить целевого бота', error=str(error))
            if not settings.BOT_MIGRATION_ENABLED:
                return await handler(event, data)
            return None
        if identity.username and identity.username.lower() == migration_target_username():
            if isinstance(event, Message) and data.get('state'):
                parts = (event.text or '').split()
                token = extract_migration_token(parts[1] if len(parts) > 1 else None)
                if token and parts[0].split('@')[0] == '/start':
                    # Keep separate from first-touch campaign payload during channel gates.
                    await data['state'].update_data(pending_migration_token=token)
            return await handler(event, data)
        if not settings.BOT_MIGRATION_ENABLED:
            return await handler(event, data)

        # A stale callback answer must not prevent sending the actual URL button.
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logger.debug('Не удалось закрыть callback переезда', user_id=user.id, error=str(error))

        try:
            url = validate_migration_value('BOT_MIGRATION_URL', settings.BOT_MIGRATION_URL)
            amount = 0
            if settings.BOT_MIGRATION_BONUS_ENABLED:
                try:
                    async with AsyncSessionLocal() as db:
                        link = await issue_migration_link(db, user.id, bot.id)
                    url, amount = link.url, link.amount_kopeks
                except Exception as error:
                    logger.error('Не удалось выдать ссылку с бонусом переезда', user_id=user.id, error=str(error))
                    await bot.send_message(
                        user.id, 'Не удалось подготовить ссылку переезда. Попробуйте ещё раз чуть позже.'
                    )
                    return None
            text = render_migration_text(settings.BOT_MIGRATION_MESSAGE, amount)
            button_text = render_migration_text(settings.BOT_MIGRATION_BUTTON_TEXT, amount)
            if settings.BOT_MIGRATION_BONUS_ENABLED and amount == 0:
                text = settings.BOT_MIGRATION_NO_BONUS_MESSAGE
                button_text = settings.BOT_MIGRATION_NO_BONUS_BUTTON_TEXT
            markup = (
                InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=url)]])
                if url
                else None
            )
            # Plain text: admin-provided text cannot break Telegram HTML parsing.
            if isinstance(event, Message):
                await event.answer(text, reply_markup=markup, parse_mode=None)
            else:
                # Send to the callback author, not an arbitrary/inline message chat.
                await bot.send_message(user.id, text, reply_markup=markup, parse_mode=None)
        except TelegramForbiddenError as error:
            logger.debug('Заглушка переезда не доставлена', user_id=user.id, error=str(error))
        except TelegramBadRequest as error:
            log = logger.debug if is_user_unreachable(error) else logger.error
            log('Ошибка доставки заглушки переезда', user_id=user.id, error=str(error))
        except ValueError as error:
            logger.error('Некорректная настройка переезда', error=str(error))
        return None
