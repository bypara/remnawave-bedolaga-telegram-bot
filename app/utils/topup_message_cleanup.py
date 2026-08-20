"""Track and remove intermediate messages from a manual balance top-up flow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ManualTopupMessages:
    chat_id: int
    user_message_id: int
    prompt_message_id: int | None


_current_manual_topup: ContextVar[ManualTopupMessages | None] = ContextVar(
    'current_manual_topup',
    default=None,
)


@contextmanager
def manual_topup_messages(
    *,
    chat_id: int,
    user_message_id: int,
    prompt_message_id: int | None,
) -> Iterator[ManualTopupMessages]:
    """Expose the two disposable messages while a provider creates an invoice."""
    messages = ManualTopupMessages(
        chat_id=chat_id,
        user_message_id=user_message_id,
        prompt_message_id=prompt_message_id,
    )
    token = _current_manual_topup.set(messages)
    try:
        yield messages
    finally:
        _current_manual_topup.reset(token)


def get_manual_topup_messages() -> ManualTopupMessages | None:
    return _current_manual_topup.get()


async def delete_manual_topup_messages(
    bot: Bot,
    messages: ManualTopupMessages,
    *,
    keep_message_id: int | None = None,
) -> None:
    """Delete the user's amount and the preceding prompt, ignoring stale messages."""
    message_ids = dict.fromkeys((messages.user_message_id, messages.prompt_message_id))
    for message_id in message_ids:
        if message_id is None or message_id == keep_message_id:
            continue
        try:
            await bot.delete_message(messages.chat_id, message_id)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.debug(
                'Intermediate top-up message was already unavailable',
                chat_id=messages.chat_id,
                message_id=message_id,
                error=str(error),
            )
