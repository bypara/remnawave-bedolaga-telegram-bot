"""Render configurable migration messages as Telegram HTML safely."""

from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from typing import Any

import structlog
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest


logger = structlog.get_logger(__name__)


class _PlainMigrationText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


async def send_migration_message(send: Callable[..., Awaitable[Any]], text: str, **kwargs: Any) -> Any:
    try:
        return await send(text, **kwargs, parse_mode=ParseMode.HTML)
    except TelegramBadRequest as error:
        # Retry only a rejected entity/HTML parse, never an unrelated delivery failure.
        if "can't parse entities" not in str(error).lower():
            raise
        logger.warning('Некорректный HTML в сообщении переезда, отправляем обычный текст')
        parser = _PlainMigrationText()
        parser.feed(text)
        parser.close()
        plain_text = ''.join(parser.parts).strip() or text
        return await send(plain_text, **kwargs, parse_mode=None)
