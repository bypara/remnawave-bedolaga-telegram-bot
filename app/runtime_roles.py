"""Deployment roles, deliberately not mutable through shared admin settings."""

from app.config import settings


def is_primary_process() -> bool:
    return settings.BOT_PROCESS_ROLE == 'primary'


def require_primary_process() -> None:
    if not is_primary_process():
        raise RuntimeError('main.py доступен только primary-процессу. Используйте python -m app.interactive_bot.')


def interactive_allowed_ids() -> frozenset[int]:
    parts = settings.BOT_INTERACTIVE_ALLOWED_IDS.split(',')
    try:
        ids = frozenset(int(part.strip()) for part in parts if part.strip())
    except ValueError as error:
        raise ValueError('BOT_INTERACTIVE_ALLOWED_IDS должен содержать числовые Telegram ID через запятую') from error
    if not ids or any(value <= 0 for value in ids):
        raise ValueError('Для тестового бота задайте непустой список положительных BOT_INTERACTIVE_ALLOWED_IDS')
    return ids
