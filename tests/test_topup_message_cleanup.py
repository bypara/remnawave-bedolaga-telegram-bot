from datetime import UTC, datetime
from unittest.mock import AsyncMock, call

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from app.handlers.balance.payment_ui import PAY_BUTTON_EMOJI_ID
from app.middlewares.topup_prompt import TopupPromptTrackingMiddleware
from app.states import BalanceStates
from app.utils.custom_emoji_buttons import _has_payment_url
from app.utils.topup_message_cleanup import (
    ManualTopupMessages,
    delete_manual_topup_messages,
    get_manual_topup_messages,
    manual_topup_messages,
)


def test_manual_topup_context_is_limited_to_payment_creation() -> None:
    assert get_manual_topup_messages() is None

    with manual_topup_messages(chat_id=10, user_message_id=20, prompt_message_id=19) as messages:
        assert get_manual_topup_messages() == messages

    assert get_manual_topup_messages() is None


@pytest.mark.asyncio
async def test_intermediate_topup_messages_are_deleted_once() -> None:
    bot = AsyncMock()
    messages = ManualTopupMessages(chat_id=10, user_message_id=20, prompt_message_id=19)

    await delete_manual_topup_messages(bot, messages)

    assert bot.delete_message.await_args_list == [call(10, 20), call(10, 19)]


@pytest.mark.asyncio
async def test_invoice_message_is_never_deleted_when_ids_match() -> None:
    bot = AsyncMock()
    messages = ManualTopupMessages(chat_id=10, user_message_id=20, prompt_message_id=19)

    await delete_manual_topup_messages(bot, messages, keep_message_id=20)

    bot.delete_message.assert_awaited_once_with(10, 19)


def test_only_payment_url_button_triggers_cleanup() -> None:
    payment_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='Оплатить',
                    url='https://pay.example/invoice',
                    icon_custom_emoji_id=PAY_BUTTON_EMOJI_ID,
                )
            ]
        ]
    )
    support_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='Поддержка',
                    url='https://t.me/support',
                    icon_custom_emoji_id='5253742260054409879',
                )
            ]
        ]
    )

    assert _has_payment_url(payment_markup) is True
    assert _has_payment_url(support_markup) is False


@pytest.mark.asyncio
async def test_amount_prompt_is_remembered_after_provider_callback() -> None:
    storage = MemoryStorage()
    state = FSMContext(
        storage=storage,
        key=StorageKey(bot_id=1, chat_id=10, user_id=20),
    )
    message = Message(
        message_id=30,
        date=datetime.now(UTC),
        chat=Chat(id=10, type='private'),
    )
    callback = CallbackQuery(
        id='callback-id',
        from_user=User(id=20, is_bot=False, first_name='User'),
        chat_instance='chat-instance',
        message=message,
        data='topup_lava_sbp',
    )
    middleware = TopupPromptTrackingMiddleware()

    async def handler(_event, _data):
        await state.set_state(BalanceStates.waiting_for_amount)
        return 'handled'

    result = await middleware(handler, callback, {'state': state})

    assert result == 'handled'
    assert await state.get_data() == {
        'topup_prompt_chat_id': 10,
        'topup_prompt_message_id': 30,
    }
