"""Explicit outbound identity; no polling, webhook setup or business workers."""

from app.config import settings


def get_broadcast_sender_token(sender: str) -> str:
    if sender == 'current':
        return settings.BOT_TOKEN
    if sender != 'legacy':
        raise ValueError('Неизвестный отправитель рассылки')
    if not settings.LEGACY_BOT_TOKEN:
        raise ValueError('Токен старого бота ещё не настроен (LEGACY_BOT_TOKEN)')
    return settings.LEGACY_BOT_TOKEN
