from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User
from aiohttp.test_utils import TestClient, TestServer

from app import interactive_bot as interactive
from app.config import Settings, settings
from app.runtime_roles import interactive_allowed_ids, require_primary_process
from app.services.system_settings_service import BotConfigurationService


TEST_TOKEN = '456:test-token'


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        'BOT_PROCESS_ROLE': 'interactive',
        'BOT_PRIMARY_ID': 123,
        'BOT_USERNAME': 'newbot',
        'BOT_INTERACTIVE_ALLOWED_IDS': '42,43',
        'BOT_INTERACTIVE_PUBLIC_ACCESS': False,
        'BOT_INTERACTIVE_ADMIN_ENABLED': False,
        'BOT_RUN_MODE': 'polling',
        'DATABASE_URL': 'postgresql+asyncpg://user:pass@localhost/test_db',
        'BOT_MIGRATION_ENABLED': False,
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(Message, 'answer', AsyncMock())
    monkeypatch.setattr(CallbackQuery, 'answer', AsyncMock())
    monkeypatch.setattr(PreCheckoutQuery, 'answer', AsyncMock())


def message(user_id=42, **kwargs):
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=user_id, type=ChatType.PRIVATE),
        from_user=User(id=user_id, is_bot=False, first_name='User'),
        **kwargs,
    )


def middleware():
    loader = SimpleNamespace(reload=AsyncMock())
    return interactive.InteractiveAccessMiddleware(frozenset({42}), loader), loader


def test_default_role_keeps_existing_primary_behavior():
    assert Settings.model_fields['BOT_PROCESS_ROLE'].default == 'primary'


def test_private_role_can_start_while_migration_disabled(configured):
    assert interactive.validate_interactive_config() == frozenset({42, 43})
    assert settings.BOT_MIGRATION_ENABLED is False
    with pytest.raises(RuntimeError, match=r'main\.py'):
        require_primary_process()


@pytest.mark.parametrize('value', ['', '0', '-1', '42,nope'])
def test_allowlist_must_be_explicit_and_valid(configured, monkeypatch, value):
    monkeypatch.setattr(settings, 'BOT_INTERACTIVE_ALLOWED_IDS', value)
    with pytest.raises(ValueError):
        interactive_allowed_ids()


def test_public_access_requires_explicit_flag(configured, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_INTERACTIVE_PUBLIC_ACCESS', True)
    monkeypatch.setattr(settings, 'BOT_INTERACTIVE_ALLOWED_IDS', '')
    assert interactive.validate_interactive_config() is None


async def test_public_access_allows_foreign_users_callbacks_and_precheckout(configured):
    loader = SimpleNamespace(reload=AsyncMock())
    access = interactive.InteractiveAccessMiddleware(None, loader)
    handler = AsyncMock(return_value='normal')
    user = message(99).from_user
    events = [
        Update(update_id=1, message=message(99, text='/start')),
        Update(update_id=2, callback_query=CallbackQuery(id='q', from_user=user, chat_instance='c', data='menu')),
        Update(
            update_id=3,
            pre_checkout_query=PreCheckoutQuery(
                id='p', from_user=user, currency='XTR', total_amount=1, invoice_payload='test'
            ),
        ),
    ]
    for event in events:
        assert await access(handler, event, {}) == 'normal'
    assert handler.await_count == 3
    assert loader.reload.await_count == 3
    PreCheckoutQuery.answer.assert_not_awaited()


async def test_public_mode_still_ignores_groups_and_monitoring(configured):
    loader = SimpleNamespace(reload=AsyncMock())
    access = interactive.InteractiveAccessMiddleware(None, loader)
    handler = AsyncMock()
    group = message(99, text='/start').model_copy(update={'chat': Chat(id=-42, type=ChatType.GROUP)})
    await access(handler, Update(update_id=1, message=group), {})
    callback = CallbackQuery(id='q', from_user=message().from_user, chat_instance='c', data='maintenance_monitoring')
    await access(handler, Update(update_id=2, callback_query=callback), {})
    handler.assert_not_awaited()
    loader.reload.assert_not_awaited()
    CallbackQuery.answer.assert_awaited_once()


@pytest.mark.parametrize(
    'key,value',
    [
        ('BOT_PROCESS_ROLE', 'primary'),
        ('BOT_PRIMARY_ID', 0),
        ('BOT_USERNAME', ''),
        ('DATABASE_URL', 'sqlite:///local.db'),
    ],
)
async def test_invalid_configuration_does_not_create_or_touch_bot(configured, monkeypatch, key, value):
    monkeypatch.setattr(settings, key, value)
    create = Mock()
    monkeypatch.setattr(interactive, 'create_bot', create)
    with pytest.raises(ValueError):
        await interactive.main()
    create.assert_not_called()


async def test_primary_token_rejected_before_identity_or_webhook(configured):
    bot = SimpleNamespace(id=123, me=AsyncMock(), set_webhook=AsyncMock(), delete_webhook=AsyncMock())
    with pytest.raises(ValueError, match='основного бота'):
        await interactive.validate_interactive_identity(bot, 'newbot')
    bot.me.assert_not_awaited()
    bot.set_webhook.assert_not_awaited()
    bot.delete_webhook.assert_not_awaited()


async def test_wrong_username_rejected_before_database(configured, monkeypatch):
    bot = SimpleNamespace(id=456, me=AsyncMock(return_value=SimpleNamespace(id=456, username='wrongbot')))
    connect = Mock()
    monkeypatch.setattr(interactive, 'engine', SimpleNamespace(connect=connect))
    with pytest.raises(ValueError, match='ожидаемому'):
        await interactive.validate_interactive_identity(bot, 'newbot')
    connect.assert_not_called()


@pytest.mark.parametrize('revision,valid', [('0134', True), ('0133', False)])
async def test_schema_checked_read_only_never_migrated(configured, monkeypatch, revision, valid):
    bot = SimpleNamespace(id=456, me=AsyncMock(return_value=SimpleNamespace(id=456, username='NEWBOT')))
    connection = AsyncMock()
    connection.execute.return_value = SimpleNamespace(scalar_one=lambda: revision)

    # Special methods must live on the type, not a SimpleNamespace instance.
    class Connection:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(interactive, 'engine', SimpleNamespace(connect=lambda: Connection()))
    if valid:
        await interactive.validate_interactive_identity(bot, 'newbot')
    else:
        with pytest.raises(ValueError, match='схему'):
            await interactive.validate_interactive_identity(bot, 'newbot')
    connection.execute.assert_awaited_once()
    assert str(connection.execute.call_args.args[0]).startswith('SELECT')
    connection.commit.assert_not_awaited()


async def test_allowed_start_uses_normal_handlers_and_does_not_enable_migration(configured):
    access, loader = middleware()
    handler = AsyncMock(return_value='normal')
    assert await access(handler, Update(update_id=1, message=message(text='/start')), {}) == 'normal'
    handler.assert_awaited_once()
    loader.reload.assert_awaited_once()
    assert settings.BOT_MIGRATION_ENABLED is False


async def test_foreign_messages_callbacks_and_precheckout_blocked_before_db(configured):
    access, loader = middleware()
    handler = AsyncMock()
    user = message(99).from_user
    events = [
        Update(update_id=1, message=message(99, text='/start')),
        Update(update_id=2, callback_query=CallbackQuery(id='q', from_user=user, chat_instance='c', data='menu')),
        Update(
            update_id=3,
            pre_checkout_query=PreCheckoutQuery(
                id='p', from_user=user, currency='XTR', total_amount=1, invoice_payload='test'
            ),
        ),
    ]
    for event in events:
        assert await access(handler, event, {}) is None
    Message.answer.assert_awaited_once()
    CallbackQuery.answer.assert_awaited_once()
    assert PreCheckoutQuery.answer.call_args.kwargs['ok'] is False
    loader.reload.assert_not_awaited()
    handler.assert_not_awaited()


async def test_completed_payment_not_lost_after_test_allowlist_removed(configured):
    access, loader = middleware()
    handler = AsyncMock()
    payment = SuccessfulPayment(
        currency='XTR',
        total_amount=1,
        invoice_payload='test',
        telegram_payment_charge_id='tg',
        provider_payment_charge_id='provider',
    )
    await access(handler, Update(update_id=1, message=message(99, successful_payment=payment)), {})
    handler.assert_awaited_once()
    loader.reload.assert_awaited_once()


async def test_allowed_group_message_ignored(configured):
    access, loader = middleware()
    handler = AsyncMock()
    group = message(text='/start').model_copy(update={'chat': Chat(id=-42, type=ChatType.GROUP)})
    await access(handler, Update(update_id=1, message=group), {})
    handler.assert_not_awaited()
    loader.reload.assert_not_awaited()


async def test_live_settings_reload_is_read_only_and_freezes_bot_identity(configured, monkeypatch):
    loader = interactive.InteractiveSettingsLoader('newbot')

    async def shared_reload():
        settings.BOT_USERNAME = 'oldbot'

    monkeypatch.setattr(loader.reader, 'reload', shared_reload)
    from app.services.maintenance_service import maintenance_service

    passive = AsyncMock()
    monkeypatch.setattr(maintenance_service, 'refresh_passive_status', passive)
    await loader.reload()
    assert settings.BOT_USERNAME == 'newbot'
    passive.assert_awaited_once()


def test_deployment_roles_are_not_editable_in_shared_admin_settings():
    assert {
        'BOT_PROCESS_ROLE',
        'BOT_PRIMARY_ID',
        'BOT_INTERACTIVE_ALLOWED_IDS',
        'BOT_INTERACTIVE_PUBLIC_ACCESS',
        'BOT_INTERACTIVE_ADMIN_ENABLED',
    } <= BotConfigurationService.EXCLUDED_KEYS


async def test_health_only_server_has_no_cabinet_payment_or_panel_routes(configured):
    bot = Bot(TEST_TOKEN)
    dp = Dispatcher()
    client = TestClient(TestServer(interactive.build_web_app(dp, bot, path=None, secret=None)))
    try:
        await client.start_server()
        response = await client.get('/health')
        assert response.status == 200
        assert (await response.json())['business_workers'] is False
        for path in ('/api/cabinet/branding', '/platega-webhook', '/remnawave-webhook'):
            assert (await client.post(path, json={})).status == 404
    finally:
        await client.close()
        await bot.session.close()
        await dp.storage.close()


async def test_public_admin_health_reports_actual_mode(configured, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_INTERACTIVE_PUBLIC_ACCESS', True)
    monkeypatch.setattr(settings, 'BOT_INTERACTIVE_ADMIN_ENABLED', True)
    bot = Bot(TEST_TOKEN)
    dp = Dispatcher()
    client = TestClient(TestServer(interactive.build_web_app(dp, bot, path=None, secret=None)))
    try:
        await client.start_server()
        result = await (await client.get('/health')).json()
        assert result['private_test'] is False
        assert result['admin_enabled'] is True
        assert result['business_workers'] is False
    finally:
        await client.close()
        await bot.session.close()
        await dp.storage.close()


async def test_webhook_requires_secret_and_never_handles_unverified_update(configured):
    bot = Bot(TEST_TOKEN)
    dp = Dispatcher()
    feed = AsyncMock()
    dp.feed_webhook_update = feed
    client = TestClient(TestServer(interactive.build_web_app(dp, bot, path='/new-webhook', secret='test-secret')))
    try:
        await client.start_server()
        response = await client.post('/new-webhook', json={'update_id': 1})
        assert response.status == 401
        feed.assert_not_awaited()
    finally:
        await client.close()
        await bot.session.close()
        await dp.storage.close()
