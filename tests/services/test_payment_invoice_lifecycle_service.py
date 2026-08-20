from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.payment_invoice_lifecycle_service import (
    LIFECYCLE_METADATA_KEY,
    _extract_payment_urls,
    _is_paid,
    _is_pending,
    _send_expired,
    _send_warning,
    delete_paid_invoice_messages,
)


def test_extract_payment_urls_ignores_callback_buttons():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Pay', url='https://pay.example/invoice')],
            [InlineKeyboardButton(text='Back', callback_data='back_to_menu')],
        ]
    )

    assert _extract_payment_urls(markup) == {'https://pay.example/invoice'}


@pytest.mark.parametrize(
    ('status', 'is_paid', 'expected_paid', 'expected_pending'),
    [
        ('pending', False, False, True),
        ('check', False, False, True),
        ('success', True, True, False),
        ('expired', False, False, False),
    ],
)
def test_payment_state_classification(status, is_paid, expected_paid, expected_pending):
    payment = SimpleNamespace(status=status, is_paid=is_paid)

    assert _is_paid(payment) is expected_paid
    assert _is_pending(payment) is expected_pending


@pytest.mark.asyncio
async def test_warning_keeps_original_invoice_and_records_warning_message():
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=22)))
    db = SimpleNamespace(commit=AsyncMock())
    payment = SimpleNamespace(payment_url='https://pay.example/1', metadata_json={})
    user = SimpleNamespace(language='ru')
    lifecycle = {'chat_id': 100, 'invoice_message_id': 11}

    await _send_warning(bot, db, payment, user, lifecycle)

    stored = payment.metadata_json[LIFECYCLE_METADATA_KEY]
    assert stored['invoice_message_id'] == 11
    assert stored['warning_message_id'] == 22
    assert stored['warned_at']
    sent_markup = bot.send_message.await_args.kwargs['reply_markup']
    assert sent_markup.inline_keyboard[0][0].url == 'https://pay.example/1#payment-expiry-reminder'


@pytest.mark.asyncio
async def test_expiry_deletes_invoice_and_warning_then_sends_main_menu():
    bot = SimpleNamespace(
        delete_message=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=33)),
    )
    db = SimpleNamespace(commit=AsyncMock())
    payment = SimpleNamespace(metadata_json={}, amount_kopeks=12_300)
    user = SimpleNamespace(language='en')
    lifecycle = {'chat_id': 100, 'invoice_message_id': 11, 'warning_message_id': 22}

    await _send_expired(bot, db, payment, user, lifecycle)

    deleted_ids = [call.kwargs['message_id'] for call in bot.delete_message.await_args_list]
    assert deleted_ids == [11, 22]
    sent_markup = bot.send_message.await_args.kwargs['reply_markup']
    assert sent_markup.inline_keyboard[0][0].callback_data == 'back_to_menu'
    assert 'Invoice amount: 123' in bot.send_message.await_args.kwargs['text']
    stored = payment.metadata_json[LIFECYCLE_METADATA_KEY]
    assert stored['expired_message_id'] == 33
    assert stored['expired_notified_at']


@pytest.mark.asyncio
async def test_successful_payment_deletes_invoice_and_warning_immediately():
    bot = SimpleNamespace(delete_message=AsyncMock())
    payment = SimpleNamespace(
        metadata_json={
            LIFECYCLE_METADATA_KEY: {
                'chat_id': 100,
                'invoice_message_id': 11,
                'warning_message_id': 22,
            }
        }
    )

    await delete_paid_invoice_messages(bot, payment)

    deleted_ids = [call.kwargs['message_id'] for call in bot.delete_message.await_args_list]
    assert deleted_ids == [11, 22]
