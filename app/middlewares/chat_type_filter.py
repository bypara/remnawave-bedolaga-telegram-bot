"""Middleware to ignore non-private chat messages.

When the bot is added as admin to a group or supergroup (including forums
with topics), it should silently drop incoming messages and ordinary callback
queries from those chats. Admin callbacks in the configured notification chat
are allowed so notification action buttons keep working.

Not registered on chat_member — channel_member.py needs ChatMemberUpdated
events from groups/channels to track required channel subscriptions.
Not registered on pre_checkout_query — no chat context, always private.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings


logger = structlog.get_logger(__name__)


class ChatTypeFilterMiddleware(BaseMiddleware):
    """Drop non-private events except trusted admin-chat callbacks."""

    @staticmethod
    def _is_trusted_admin_callback(event: TelegramObject, chat_id: int) -> bool:
        if not isinstance(event, CallbackQuery) or not event.data or not event.from_user:
            return False

        admin_chat_id = getattr(settings, 'ADMIN_NOTIFICATIONS_CHAT_ID', None)
        return (
            admin_chat_id is not None
            and chat_id == admin_chat_id
            and event.data.startswith('admin_')
            and settings.is_admin(event.from_user.id)
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat

        if (
            chat is not None
            and chat.type != ChatType.PRIVATE
            and not self._is_trusted_admin_callback(event, chat.id)
        ):
            logger.debug(
                'Dropping non-private chat event',
                chat_id=chat.id,
                chat_type=chat.type,
            )
            return None

        return await handler(event, data)
