from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from app.config import settings
from app.services import legacy_notification_service
from app.services.bot_migration_service import MigrationLink
from app.services.monitoring_service import MonitoringService


class _DbContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *_args):
        return False


def _legacy_bot():
    bot = MagicMock()
    bot.id = 123456

    async def send_message(chat_id, text, **_kwargs):
        return SimpleNamespace(message_id=77, chat_id=chat_id, text=text)

    bot.send_message = AsyncMock(side_effect=send_message)
    bot.session.close = AsyncMock()
    return bot


@pytest.fixture
def migration_settings(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', True)
    monkeypatch.setattr(settings, 'LEGACY_BOT_TOKEN', '123456:legacy')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/new_service_bot')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_MESSAGE', '<b>Мы переехали</b>')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BUTTON_TEXT', 'Перейти и получить {bonus} ₽')


async def test_legacy_delivery_adds_personal_migration_button(monkeypatch, migration_settings):
    legacy = _legacy_bot()
    monkeypatch.setattr(legacy_notification_service, 'Bot', lambda _token: legacy)
    monkeypatch.setattr(legacy_notification_service, 'AsyncSessionLocal', _DbContext)
    monkeypatch.setattr(
        legacy_notification_service,
        'issue_migration_link',
        AsyncMock(return_value=MigrationLink('https://t.me/new_service_bot?start=move_token', 5000)),
    )

    result = await legacy_notification_service.send_notification_through_legacy_bot(
        telegram_id=42,
        text='<b>Подписка скоро закончится</b>',
    )

    assert result.message_id == 77
    assert result.chat_id == 42
    call = legacy.send_message.await_args
    assert call.kwargs['chat_id'] == 42
    assert call.kwargs['text'] == '<b>Подписка скоро закончится</b>\n\n<b>Мы переехали</b>'
    button = call.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == 'Перейти и получить 50 ₽'
    assert button.url.endswith('?start=move_token')
    legacy.session.close.assert_awaited_once()


async def test_monitoring_falls_back_only_when_new_bot_has_no_chat(monkeypatch, migration_settings):
    primary = MagicMock()
    primary.send_message = AsyncMock(
        side_effect=TelegramBadRequest(method=SendMessage(chat_id=42, text='x'), message='chat not found')
    )
    service = MonitoringService(primary)
    legacy_send = AsyncMock(return_value=SimpleNamespace(message_id=77))
    monkeypatch.setattr('app.services.monitoring_service.try_send_rich_notification', AsyncMock(return_value=False))
    monkeypatch.setattr('app.services.monitoring_service.send_notification_through_legacy_bot', legacy_send)
    monkeypatch.setattr(settings, 'ENABLE_LOGO_MODE', False)

    result = await service._send_message_with_logo(42, 'Срок скоро закончится', user=SimpleNamespace(status='active'))

    assert result.message_id == 77
    legacy_send.assert_awaited_once_with(telegram_id=42, text='Срок скоро закончится')


async def test_explicit_new_bot_block_is_not_bypassed(monkeypatch, migration_settings):
    primary = MagicMock()
    primary.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=SendMessage(chat_id=42, text='x'), message='bot was blocked')
    )
    service = MonitoringService(primary)
    legacy_send = AsyncMock()
    monkeypatch.setattr('app.services.monitoring_service.try_send_rich_notification', AsyncMock(return_value=False))
    monkeypatch.setattr('app.services.monitoring_service.send_notification_through_legacy_bot', legacy_send)
    monkeypatch.setattr(settings, 'ENABLE_LOGO_MODE', False)

    with pytest.raises(TelegramForbiddenError):
        await service._send_message_with_logo(42, 'Текст', user=SimpleNamespace(status='active'))
    legacy_send.assert_not_awaited()
