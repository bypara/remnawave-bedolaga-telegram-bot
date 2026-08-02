from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


logger = structlog.get_logger(__name__)

SLOW_OPERATION_SECONDS = 1.0
NOTICEABLE_CALLBACK_SECONDS = 0.3


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start_time = monotonic()

        try:
            if isinstance(event, Message) and event.from_user:
                user_info = f'@{event.from_user.username}' if event.from_user.username else f'ID:{event.from_user.id}'
                text = event.text or event.caption or '[медиа]'
                logger.info('📩 Входящее сообщение', user_info=user_info, text=text)

            elif isinstance(event, CallbackQuery) and event.from_user:
                user_info = f'@{event.from_user.username}' if event.from_user.username else f'ID:{event.from_user.id}'
                logger.info('🔘 Входящий callback', user_info=user_info, event_data=event.data)

            result = await handler(event, data)

            execution_time = monotonic() - start_time
            if execution_time > SLOW_OPERATION_SECONDS:
                logger.warning('⏱️ Медленная операция', execution_time=round(execution_time, 2))
            elif isinstance(event, CallbackQuery) and execution_time > NOTICEABLE_CALLBACK_SECONDS:
                logger.info(
                    'Callback обработан с задержкой',
                    event_data=event.data,
                    execution_time_ms=round(execution_time * 1000),
                )

            return result

        except Exception as e:
            execution_time = monotonic() - start_time
            logger.exception('❌ Ошибка при обработке события', execution_time=round(execution_time, 2), error=e)
            raise
