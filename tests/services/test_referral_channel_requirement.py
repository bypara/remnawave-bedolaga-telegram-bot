from types import SimpleNamespace

from app.services import channel_subscription_service


def test_regular_user_is_not_gated_when_only_referral_retention_is_enabled(monkeypatch):
    monkeypatch.setattr(channel_subscription_service.settings, 'CHANNEL_IS_REQUIRED_SUB', False)
    monkeypatch.setattr(channel_subscription_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', True)

    user = SimpleNamespace(referred_by_id=None)

    assert channel_subscription_service.is_channel_subscription_required_for_user(user) is False


def test_referred_user_is_gated_when_referral_retention_is_enabled(monkeypatch):
    monkeypatch.setattr(channel_subscription_service.settings, 'CHANNEL_IS_REQUIRED_SUB', False)
    monkeypatch.setattr(channel_subscription_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', True)

    user = SimpleNamespace(referred_by_id=42)

    assert channel_subscription_service.is_channel_subscription_required_for_user(user) is True


def test_referred_user_is_still_gated_when_retention_reward_is_disabled(monkeypatch):
    monkeypatch.setattr(channel_subscription_service.settings, 'CHANNEL_IS_REQUIRED_SUB', False)
    monkeypatch.setattr(channel_subscription_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', False)

    user = SimpleNamespace(referred_by_id=42)

    assert channel_subscription_service.is_channel_subscription_required_for_user(user) is True


def test_global_channel_gate_still_applies_to_regular_users(monkeypatch):
    monkeypatch.setattr(channel_subscription_service.settings, 'CHANNEL_IS_REQUIRED_SUB', True)
    monkeypatch.setattr(channel_subscription_service.settings, 'REFERRAL_RETENTION_REWARD_ENABLED', False)

    user = SimpleNamespace(referred_by_id=None)

    assert channel_subscription_service.is_channel_subscription_required_for_user(user) is True
