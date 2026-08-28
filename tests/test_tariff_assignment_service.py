from datetime import UTC, datetime, timedelta

from app.database.models import Subscription, Tariff
from app.services.tariff_assignment_service import apply_tariff_limits, move_to_tariff, preview_limits


def _subscription(**overrides) -> Subscription:
    values = {
        'user_id': 1,
        'status': 'active',
        'is_trial': False,
        'end_date': datetime.now(UTC) + timedelta(days=7),
        'tariff_id': 1,
        'traffic_limit_gb': 120,
        'purchased_traffic_gb': 20,
        'device_limit': 3,
        'applied_tariff_traffic_gb': 100,
        'applied_tariff_device_limit': 1,
        'connected_squads': ['old'],
    }
    values.update(overrides)
    return Subscription(**values)


def _tariff(**overrides) -> Tariff:
    values = {
        'id': 2,
        'name': 'New',
        'traffic_limit_gb': 200,
        'device_limit': 2,
        'allowed_squads': ['new'],
    }
    values.update(overrides)
    return Tariff(**values)


def test_preview_and_apply_preserve_paid_addons() -> None:
    subscription = _subscription()
    tariff = _tariff()

    change = preview_limits(subscription, tariff)

    assert change.new_traffic_gb == 220
    assert change.new_device_limit == 4
    assert change.preserved_traffic_gb == 20
    assert change.preserved_devices == 2

    apply_tariff_limits(subscription, tariff)
    assert subscription.traffic_limit_gb == 220
    assert subscription.device_limit == 4
    assert subscription.applied_tariff_traffic_gb == 200
    assert subscription.applied_tariff_device_limit == 2


def test_move_preserves_period_status_usage_and_changes_squads() -> None:
    end_date = datetime.now(UTC) + timedelta(hours=5)
    subscription = _subscription(end_date=end_date, is_trial=True, status='trial', traffic_used_gb=42.5)

    move_to_tariff(subscription, _tariff())

    assert subscription.tariff_id == 2
    assert subscription.end_date == end_date
    assert subscription.is_trial is True
    assert subscription.status == 'trial'
    assert subscription.traffic_used_gb == 42.5
    assert subscription.connected_squads == ['new']


def test_unlimited_target_stays_unlimited_with_purchased_traffic() -> None:
    subscription = _subscription()
    apply_tariff_limits(subscription, _tariff(traffic_limit_gb=0))
    assert subscription.traffic_limit_gb == 0
    assert subscription.purchased_traffic_gb == 20


def test_legacy_device_limit_is_never_reduced() -> None:
    subscription = _subscription(applied_tariff_device_limit=None, device_limit=5)
    change = preview_limits(subscription, _tariff(device_limit=2))
    assert change.legacy_device_baseline is True
    assert change.new_device_limit >= 5
