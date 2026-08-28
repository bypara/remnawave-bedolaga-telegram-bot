"""Safe tariff migration and subscriber limit synchronization.

Tariffs are templates while subscriptions contain effective limits.  This
module is the single place that translates a changed template into effective
subscription values without silently dropping paid add-ons.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.database.models import Subscription, Tariff


@dataclass(slots=True)
class LimitChange:
    traffic_changed: bool
    devices_changed: bool
    old_traffic_gb: int
    new_traffic_gb: int
    old_device_limit: int
    new_device_limit: int
    preserved_traffic_gb: int
    preserved_devices: int
    legacy_device_baseline: bool = False

    @property
    def changed(self) -> bool:
        return self.traffic_changed or self.devices_changed


def _traffic_extras(subscription: Subscription, old_base: int) -> int:
    purchased = max(int(getattr(subscription, 'purchased_traffic_gb', 0) or 0), 0)
    if purchased:
        return purchased
    # Compatibility for rows created before TrafficPurchase accounting was
    # introduced. Unlimited (0) cannot carry a meaningful numeric difference.
    if old_base <= 0 or int(subscription.traffic_limit_gb or 0) <= 0:
        return 0
    return max(int(subscription.traffic_limit_gb or 0) - old_base, 0)


def preview_limits(subscription: Subscription, tariff: Tariff) -> LimitChange:
    old_traffic = int(subscription.traffic_limit_gb or 0)
    old_devices = int(subscription.device_limit or 0)

    applied_traffic = getattr(subscription, 'applied_tariff_traffic_gb', None)
    if applied_traffic is None:
        purchased_traffic = int(getattr(subscription, 'purchased_traffic_gb', 0) or 0)
        applied_traffic = max(old_traffic - purchased_traffic, 0)

    applied_devices = getattr(subscription, 'applied_tariff_device_limit', None)
    legacy_device_baseline = applied_devices is None
    if applied_devices is None:
        # Conservative fallback: never interpret an unexplained surplus as
        # removable. New tariff base is used only as the known minimum.
        applied_devices = min(old_devices, int(tariff.device_limit or 1))

    traffic_extras = _traffic_extras(subscription, int(applied_traffic or 0))
    device_extras = max(old_devices - int(applied_devices or 0), 0)

    new_base_traffic = int(tariff.traffic_limit_gb or 0)
    new_traffic = 0 if new_base_traffic == 0 else new_base_traffic + traffic_extras
    new_devices = max(int(tariff.device_limit or 1) + device_extras, 1)
    if tariff.max_device_limit:
        # A tariff maximum must not confiscate already purchased slots. It only
        # constrains future purchases; existing effective limits are preserved.
        new_devices = max(min(new_devices, int(tariff.max_device_limit)), old_devices)

    return LimitChange(
        traffic_changed=old_traffic != new_traffic,
        devices_changed=old_devices != new_devices,
        old_traffic_gb=old_traffic,
        new_traffic_gb=new_traffic,
        old_device_limit=old_devices,
        new_device_limit=new_devices,
        preserved_traffic_gb=traffic_extras,
        preserved_devices=device_extras,
        legacy_device_baseline=legacy_device_baseline,
    )


def apply_tariff_limits(subscription: Subscription, tariff: Tariff) -> LimitChange:
    change = preview_limits(subscription, tariff)
    subscription.traffic_limit_gb = change.new_traffic_gb
    subscription.device_limit = change.new_device_limit
    subscription.applied_tariff_traffic_gb = int(tariff.traffic_limit_gb or 0)
    subscription.applied_tariff_device_limit = int(tariff.device_limit or 1)
    return change


def move_to_tariff(subscription: Subscription, target_tariff: Tariff) -> LimitChange:
    """Relabel a subscription, preserving period, status, usage and add-ons."""
    change = apply_tariff_limits(subscription, target_tariff)
    subscription.tariff_id = target_tariff.id
    subscription.connected_squads = list(target_tariff.allowed_squads or [])
    return change
