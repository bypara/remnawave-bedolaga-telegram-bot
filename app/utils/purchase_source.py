"""Human-readable purchase origins shared by notifications and receipts."""

from typing import Any


_SOURCE_LABELS = {
    'bot': 'бот',
    'cabinet': 'личный кабинет',
    'landing': 'лендинг',
}
_SOURCE_DESCRIPTIONS = {
    'bot': 'через бота',
    'cabinet': 'через личный кабинет',
    'landing': 'через лендинг',
}


def get_purchase_source(purchase: Any) -> str:
    source = str(getattr(purchase, 'source', None) or '').strip().lower()
    if source in _SOURCE_LABELS:
        return source
    if not source and getattr(purchase, 'landing_id', None) is not None:
        return 'landing'
    return 'unknown'


def get_purchase_source_label(purchase: Any) -> str:
    return _SOURCE_LABELS.get(get_purchase_source(purchase), 'не указан')


def get_subscription_purchase_description(purchase: Any, tariff_name: str) -> str:
    origin = _SOURCE_DESCRIPTIONS.get(get_purchase_source(purchase))
    action = f'Покупка подписки {origin}' if origin else 'Покупка подписки'
    return f'{action} ({tariff_name}, {purchase.period_days} дн.)'
