"""Fallback for users who have not opened the replacement Telegram bot yet."""

from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot_migration_config import render_migration_text
from app.config import settings
from app.database.database import AsyncSessionLocal
from app.services.bot_migration_service import MigrationLink, issue_migration_link
from app.utils.migration_messages import send_migration_message


logger = structlog.get_logger(__name__)


def can_fallback_to_legacy(error: Exception) -> bool:
    """Return whether Telegram rejected delivery because the chat is unknown.

    Explicit bot blocks deliberately do not match: migration notifications must
    not bypass a user's decision to block the replacement bot.
    """
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            'chat not found',
            "bot can't initiate conversation",
            "can't initiate conversation",
        )
    )


async def send_notification_through_legacy_bot(*, telegram_id: int, text: str) -> Any | None:
    """Deliver a notification through the old bot with one migration CTA.

    The caller only uses this after the new bot reports that it cannot initiate
    a chat.  An explicit block of the new bot must never be bypassed here.
    """
    if not (
        settings.BOT_MIGRATION_ENABLED and settings.LEGACY_BOT_TOKEN and settings.BOT_MIGRATION_URL and telegram_id
    ):
        return None

    legacy_bot = Bot(settings.LEGACY_BOT_TOKEN)
    migration = MigrationLink(settings.BOT_MIGRATION_URL)
    try:
        try:
            async with AsyncSessionLocal() as db:
                migration = await issue_migration_link(db, telegram_id, legacy_bot.id)
        except Exception as error:
            # The plain migration URL remains useful if bonus-link issuance is
            # temporarily unavailable.
            logger.warning(
                'Не удалось подготовить бонусную ссылку для legacy-уведомления',
                telegram_id=telegram_id,
                error=str(error),
            )

        migration_text = render_migration_text(settings.BOT_MIGRATION_MESSAGE, migration.amount_kopeks)
        button_text = render_migration_text(settings.BOT_MIGRATION_BUTTON_TEXT, migration.amount_kopeks)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=migration.url)]])

        async def send_legacy_message(message_text: str, **send_kwargs: Any) -> Any:
            return await legacy_bot.send_message(
                chat_id=telegram_id,
                text=message_text,
                **send_kwargs,
            )

        result = await send_migration_message(
            send_legacy_message,
            f'{text.rstrip()}\n\n{migration_text}',
            reply_markup=keyboard,
        )
        logger.info('Уведомление доставлено через старого бота с кнопкой переезда', telegram_id=telegram_id)
        return result
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        logger.info(
            'Уведомление недоступно и через старого бота',
            telegram_id=telegram_id,
            error=str(error),
        )
        return None
    finally:
        await legacy_bot.session.close()
