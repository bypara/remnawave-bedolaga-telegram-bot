import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.token import TokenValidationError
from pydantic import ValidationError

from app.cabinet.routes.media import _verify_media_token, make_media_token
from app.cabinet.schemas.broadcasts import BroadcastCreateRequest, CombinedBroadcastCreateRequest
from app.config import settings
from app.services.bot_migration_service import MigrationLink
from app.services.broadcast_sender import get_broadcast_sender_token
from app.services.broadcast_service import BroadcastConfig, BroadcastMediaConfig, BroadcastService


@pytest.fixture
def migration_settings(monkeypatch):
    for name, value in {
        'BOT_TOKEN': '123:current',
        'LEGACY_BOT_TOKEN': '456:legacy',
        'BOT_MIGRATION_URL': 'https://t.me/censetbot',
        'BOT_MIGRATION_ENABLED': False,
        'BOT_MIGRATION_BONUS_ENABLED': True,
        'BOT_MIGRATION_BONUS_AMOUNT_RUBLES': 75,
        'BOT_MIGRATION_BUTTON_TEXT': 'Перейти и получить {bonus} ₽',
        'BOT_MIGRATION_NO_BONUS_BUTTON_TEXT': 'Перейти в новый бот',
    }.items():
        monkeypatch.setattr(settings, name, value)


FAKE_LEGACY_TOKEN = '456:legacy'


def fake_bot(token=FAKE_LEGACY_TOKEN, username='oldbot'):
    return SimpleNamespace(
        token=token,
        id=int(token.split(':')[0]),
        me=AsyncMock(return_value=SimpleNamespace(username=username)),
        session=SimpleNamespace(close=AsyncMock()),
        get_file=AsyncMock(),
        send_message=AsyncMock(),
        send_photo=AsyncMock(),
        send_video=AsyncMock(),
        send_document=AsyncMock(),
    )


def config(**kwargs):
    return BroadcastConfig(target='all', message_text='Переезд', selected_buttons=[], **kwargs)


def test_legacy_sender_never_silently_falls_back_to_current(migration_settings, monkeypatch):
    monkeypatch.setattr(settings, 'LEGACY_BOT_TOKEN', '')
    with pytest.raises(ValueError, match='LEGACY_BOT_TOKEN'):
        get_broadcast_sender_token('legacy')
    with pytest.raises(ValueError):
        get_broadcast_sender_token('unknown')


def test_legacy_token_is_server_only_and_masked():
    from app.services.system_settings_service import BotConfigurationService

    assert 'LEGACY_BOT_TOKEN' in BotConfigurationService.EXCLUDED_KEYS
    assert BotConfigurationService.is_secret_key('LEGACY_BOT_TOKEN')


def test_sender_is_explicit_and_current_instance_is_not_replaced(migration_settings, monkeypatch):
    service = BroadcastService()
    main = fake_bot('123:current')
    legacy = fake_bot()
    service.set_bot(main)
    factory = Mock(return_value=legacy)
    monkeypatch.setattr('app.bot_factory.create_bot', factory)
    assert service._resolve_sender('current') == (main, False)
    assert service._resolve_sender('legacy') == (legacy, True)
    factory.assert_called_once_with(token='456:legacy')
    assert service._bot is main


def test_same_token_borrows_existing_sender(migration_settings):
    service = BroadcastService()
    main = fake_bot()
    service.set_bot(main)
    assert service._resolve_sender('legacy') == (main, False)


def test_malformed_sender_token_returns_safe_validation_error(migration_settings, monkeypatch):
    monkeypatch.setattr('app.bot_factory.create_bot', Mock(side_effect=TokenValidationError('invalid')))
    with pytest.raises(ValueError, match='Некорректный токен'):
        BroadcastService()._resolve_sender('legacy')


async def test_api_rejects_unconfigured_legacy_without_creating_broadcast(migration_settings, monkeypatch):
    from fastapi import HTTPException

    from app.cabinet.routes.admin_broadcasts import create_combined_broadcast

    monkeypatch.setattr(settings, 'LEGACY_BOT_TOKEN', '')
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=list)
    db.add = Mock()
    request = CombinedBroadcastCreateRequest(
        channel='telegram', target='all', message_text='hello', telegram_sender='legacy'
    )
    with pytest.raises(HTTPException) as error:
        await create_combined_broadcast(request=request, admin=SimpleNamespace(id=1, username='admin'), db=db)
    assert error.value.status_code == 400
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_migration_button_allowed_while_stub_mode_off(migration_settings, monkeypatch):
    service = BroadcastService()
    legacy = fake_bot()
    monkeypatch.setattr('app.bot_factory.create_bot', Mock(return_value=legacy))
    await service.validate_options('legacy', True, 'file-id')
    legacy.me.assert_awaited_once()
    legacy.get_file.assert_awaited_once_with('file-id')
    legacy.session.close.assert_awaited_once()
    assert settings.BOT_MIGRATION_ENABLED is False


@pytest.mark.parametrize('sender,button', [('legacy', False), ('current', True)])
async def test_target_bot_cannot_send_old_bot_broadcast_or_move_to_itself(
    migration_settings, monkeypatch, sender, button
):
    service = BroadcastService()
    target = fake_bot('123:current', 'censetbot')
    service.set_bot(target)
    monkeypatch.setattr('app.bot_factory.create_bot', Mock(return_value=target))
    with pytest.raises(ValueError, match='целевого'):
        await service.validate_options(sender, button)


async def test_missing_target_rejected_and_owned_session_closed(migration_settings, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', '')
    legacy = fake_bot()
    monkeypatch.setattr('app.bot_factory.create_bot', Mock(return_value=legacy))
    with pytest.raises(ValueError, match='ссылку'):
        await BroadcastService().validate_options('legacy', True)
    legacy.session.close.assert_awaited_once()


async def test_ordinary_broadcast_preflight_does_not_call_telegram_or_close_main(migration_settings):
    service = BroadcastService()
    main = fake_bot('123:current', 'censetbot')
    service.set_bot(main)
    await service.validate_options('current', False)
    main.me.assert_not_awaited()
    main.session.close.assert_not_awaited()


async def test_cancelled_run_closes_only_owned_sender(migration_settings, monkeypatch):
    service = BroadcastService()
    legacy = fake_bot()
    monkeypatch.setattr('app.bot_factory.create_bot', Mock(return_value=legacy))
    monkeypatch.setattr(service, '_mark_cancelled', AsyncMock())
    cancel = asyncio.Event()
    cancel.set()
    await service._run_broadcast(1, config(telegram_sender='legacy'), cancel)
    legacy.session.close.assert_awaited_once()


async def test_personal_buttons_are_owner_specific_and_do_not_mutate_shared_keyboard(migration_settings, monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr('app.services.broadcast_service.AsyncSessionLocal', Session)
    issue = AsyncMock(
        side_effect=[
            MigrationLink('https://t.me/censetbot?start=move_first', 7550),
            MigrationLink('https://t.me/censetbot', 0),
        ]
    )
    monkeypatch.setattr('app.services.bot_migration_service.issue_migration_link', issue)
    shared = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Поддержка', callback_data='support')]])
    cfg = config(telegram_sender='legacy', add_migration_button=True, sender_bot=fake_bot())
    service = BroadcastService()
    first = await service._recipient_keyboard(101, cfg, shared)
    second = await service._recipient_keyboard(102, cfg, shared)
    assert first.inline_keyboard[-1][0].text == 'Перейти и получить 75.5 ₽'
    assert first.inline_keyboard[-1][0].url.endswith('move_first')
    assert second.inline_keyboard[-1][0].text == 'Перейти в новый бот'
    assert len(shared.inline_keyboard) == 1
    assert [(call.args[1], call.args[2]) for call in issue.await_args_list] == [(101, 456), (102, 456)]


async def test_optional_button_off_never_issues_links(migration_settings, monkeypatch):
    issue = AsyncMock()
    monkeypatch.setattr('app.services.bot_migration_service.issue_migration_link', issue)
    assert await BroadcastService()._recipient_keyboard(1, config(), None) is None
    issue.assert_not_awaited()


async def test_legacy_text_uses_captured_bot_not_main_or_rich_logo(migration_settings, monkeypatch):
    service = BroadcastService()
    main, legacy = fake_bot('123:current'), fake_bot()
    service.set_bot(main)
    rich = AsyncMock(return_value=True)
    monkeypatch.setattr('app.utils.rich_notify.try_send_rich_notification', rich)
    await service._deliver_message(101, config(telegram_sender='legacy', sender_bot=legacy), None)
    legacy.send_message.assert_awaited_once()
    main.send_message.assert_not_awaited()
    rich.assert_not_awaited()


@pytest.mark.parametrize('kind', ['photo', 'video', 'document'])
async def test_media_sent_by_selected_bot(migration_settings, kind):
    service = BroadcastService()
    main, legacy = fake_bot('123:current'), fake_bot()
    service.set_bot(main)
    await service._deliver_message(
        101,
        config(telegram_sender='legacy', sender_bot=legacy, media=BroadcastMediaConfig(type=kind, file_id='file')),
        None,
    )
    getattr(legacy, f'send_{kind}').assert_awaited_once()
    getattr(main, f'send_{kind}').assert_not_awaited()


def test_requests_default_to_existing_behavior_and_validate_sender():
    request = BroadcastCreateRequest(target='all', message_text='hello')
    assert request.telegram_sender == 'current' and request.add_migration_button is False
    combined = CombinedBroadcastCreateRequest(
        channel='telegram', target='all', message_text='hello', telegram_sender='legacy', add_migration_button=True
    )
    assert combined.telegram_sender == 'legacy'
    with pytest.raises(ValidationError):
        BroadcastCreateRequest(target='all', message_text='hello', telegram_sender='other')


@pytest.mark.parametrize('sender', ['current', 'legacy'])
def test_media_token_cannot_be_reused_with_different_sender(sender):
    token = make_media_token('A' * 32, sender)
    assert _verify_media_token('A' * 32, token, sender)
    other = 'legacy' if sender == 'current' else 'current'
    assert not _verify_media_token('A' * 32, token, other)
