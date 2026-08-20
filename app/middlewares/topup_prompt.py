"""Remember the message that asks a user to enter a top-up amount."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, types
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from app.states import BalanceStates


class TopupPromptTrackingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        if not isinstance(event, types.CallbackQuery) or not isinstance(event.message, types.Message):
            return result

        state = data.get('state')
        if not isinstance(state, FSMContext):
            return result

        if await state.get_state() == BalanceStates.waiting_for_amount.state:
            await state.update_data(
                topup_prompt_chat_id=event.message.chat.id,
                topup_prompt_message_id=event.message.message_id,
            )

        return result
