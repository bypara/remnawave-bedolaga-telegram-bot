from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import referral_retention_service


@pytest.mark.asyncio
async def test_schedule_retention_reward_snapshots_amount_and_deadline(monkeypatch):
    monkeypatch.setattr(referral_retention_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', True)
    monkeypatch.setattr(referral_retention_service.settings, 'REFERRAL_RETENTION_REWARD_KOPEKS', 12_300)
    monkeypatch.setattr(referral_retention_service.settings, 'REFERRAL_RETENTION_DAYS', 5)

    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        add=lambda value: setattr(db, 'added', value),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    before = datetime.now(UTC)
    reward = await referral_retention_service.schedule_referral_retention_reward(
        db,
        referral_id=22,
        referrer_id=11,
    )

    assert reward is db.added
    assert reward.amount_kopeks == 12_300
    assert reward.referral_id == 22
    assert reward.referrer_id == 11
    assert reward.eligible_at >= before
    assert 4.99 <= (reward.eligible_at - before).total_seconds() / 86400 <= 5.01
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_retention_reward_is_disabled_by_zero_amount(monkeypatch):
    monkeypatch.setattr(referral_retention_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', True)
    monkeypatch.setattr(referral_retention_service.settings, 'REFERRAL_RETENTION_REWARD_KOPEKS', 0)
    db = SimpleNamespace(scalar=AsyncMock(), add=lambda _value: None, commit=AsyncMock())

    reward = await referral_retention_service.schedule_referral_retention_reward(
        db,
        referral_id=22,
        referrer_id=11,
    )

    assert reward is None
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_strict_channel_check_does_not_accept_unknown(monkeypatch):
    service = referral_retention_service.channel_subscription_service
    monkeypatch.setattr(service, 'bot', object())
    monkeypatch.setattr(service, 'get_required_channels', AsyncMock(return_value=[{'channel_id': '@required'}]))
    monkeypatch.setattr(service, '_rate_limited_check', AsyncMock(return_value=None))

    fake_session = SimpleNamespace(commit=AsyncMock())

    class _Context:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        'app.services.channel_subscription_service.AsyncSessionLocal',
        lambda: _Context(),
    )

    assert await service.check_required_channels_strict(123) is None
