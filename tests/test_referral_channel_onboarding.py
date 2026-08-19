from unittest.mock import AsyncMock

import pytest

from app.handlers import start


def _channel(*, subscribed: bool) -> dict:
    return {
        'channel_id': '-100123',
        'channel_link': '@huntvpn',
        'title': 'Hunt VPN',
        'is_subscribed': subscribed,
    }


@pytest.mark.asyncio
async def test_referral_gate_stays_locked_until_membership_is_confirmed(monkeypatch):
    query = AsyncMock()
    query.from_user.id = 42
    query.message.edit_text = AsyncMock()
    state = AsyncMock()
    state.get_data.return_value = {
        'language': 'ru',
        'referral_channel_gate_pending': True,
        'referrer_id': 7,
    }
    bot = AsyncMock()
    service = start.channel_subscription_service

    monkeypatch.setattr(start, 'get_user_by_telegram_id', AsyncMock(return_value=None))
    monkeypatch.setattr(service, 'bot', bot)
    monkeypatch.setattr(service, 'invalidate_user_cache', AsyncMock())
    monkeypatch.setattr(service, 'check_required_channels_strict', AsyncMock(return_value=False))
    monkeypatch.setattr(service, 'get_channels_with_status', AsyncMock(return_value=[_channel(subscribed=False)]))
    complete = AsyncMock()
    monkeypatch.setattr(start, 'complete_registration_from_callback', complete)

    await start.required_sub_channel_check(query, bot, state, AsyncMock())

    query.message.edit_text.assert_awaited_once()
    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs['show_alert'] is True
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_referral_gate_continues_registration_after_membership(monkeypatch):
    query = AsyncMock()
    query.from_user.id = 42
    state = AsyncMock()
    state_data = {
        'language': 'ru',
        'referral_channel_gate_pending': True,
        'referral_channel_gate_message_id': 100,
        'referrer_id': 7,
    }
    state.get_data.return_value = state_data
    bot = AsyncMock()
    service = start.channel_subscription_service

    monkeypatch.setattr(start, 'get_user_by_telegram_id', AsyncMock(return_value=None))
    monkeypatch.setattr(service, 'bot', bot)
    monkeypatch.setattr(service, 'invalidate_user_cache', AsyncMock())
    monkeypatch.setattr(service, 'check_required_channels_strict', AsyncMock(return_value=True))
    monkeypatch.setattr(service, 'get_channels_with_status', AsyncMock(return_value=[_channel(subscribed=True)]))
    complete = AsyncMock()
    monkeypatch.setattr(start, 'complete_registration_from_callback', complete)

    await start.required_sub_channel_check(query, bot, state, AsyncMock())

    assert state_data['referral_channel_gate_pending'] is False
    assert state_data['referral_channel_gate_verified'] is True
    assert 'referral_channel_gate_message_id' not in state_data
    complete.assert_awaited_once()
    query.message.delete.assert_not_awaited()
