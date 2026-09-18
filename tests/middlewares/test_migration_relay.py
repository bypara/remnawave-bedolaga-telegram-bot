import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User
from aiohttp.test_utils import TestClient, TestServer

from app import migration_bot as relay
from app.config import settings
from app.services.system_settings_service import BotConfigurationService


def message(**kwargs):
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type=ChatType.PRIVATE),
        from_user=User(id=42, is_bot=False, first_name='User'),
        **kwargs,
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', True)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', False)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/new_service_bot')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_MESSAGE', 'Мы переехали')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BUTTON_TEXT', 'Перейти')
    monkeypatch.setattr(type(settings), 'is_admin', lambda _self, _id: False)
    monkeypatch.setattr(
        Bot,
        'me',
        AsyncMock(
            return_value=User(
                id=123456,
                is_bot=True,
                first_name='Old',
                username='old_service_bot',
            )
        ),
    )
    monkeypatch.setattr(Message, 'answer', AsyncMock())
    monkeypatch.setattr(Bot, 'send_message', AsyncMock())
    monkeypatch.setattr(CallbackQuery, 'answer', AsyncMock())
    return Bot('123456:test-token')


async def test_refuse_disabled_relay_before_identity_or_schema(configured, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    with pytest.raises(ValueError, match='включённом'):
        await relay.validate_relay(configured)
    Bot.me.assert_not_awaited()


async def test_refuse_missing_target(configured, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', '')
    with pytest.raises(ValueError, match='ссылку'):
        await relay.validate_relay(configured)
    Bot.me.assert_not_awaited()


async def test_refuse_target_token(configured, monkeypatch):
    monkeypatch.setattr(
        Bot,
        'me',
        AsyncMock(
            return_value=User(
                id=123456,
                is_bot=True,
                first_name='New',
                username='NEW_SERVICE_BOT',
            )
        ),
    )
    with pytest.raises(ValueError, match='СТАРОГО'):
        await relay.validate_relay(configured)


async def test_validate_checks_schema_without_migrating(configured, monkeypatch):
    db = AsyncMock()
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(relay, 'AsyncSessionLocal', session)
    await relay.validate_relay(configured)
    db.execute.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert 'LIMIT' in str(db.execute.call_args.args[0])


async def test_unknown_messages_and_callbacks_are_stubbed_including_admin(configured, monkeypatch):
    monkeypatch.setattr(type(settings), 'is_admin', lambda _self, _id: True)
    loader = SimpleNamespace(reload=AsyncMock())
    dp = relay.build_dispatcher(loader)
    try:
        await dp.feed_update(configured, Update(update_id=1, message=message(text='/unknown')))
        Message.answer.assert_awaited_once_with(
            'Мы переехали', reply_markup=Message.answer.call_args.kwargs['reply_markup'], parse_mode='HTML'
        )
        callback = CallbackQuery(id='old', from_user=message().from_user, chat_instance='chat', data='obsolete')
        await dp.feed_update(configured, Update(update_id=2, callback_query=callback))
        Bot.send_message.assert_awaited_once()
        assert Bot.send_message.call_args.args[:2] == (42, 'Мы переехали')
        assert loader.reload.await_count == 2
    finally:
        await dp.storage.close()


async def test_disable_live_does_not_activate_full_bot(configured, monkeypatch):
    async def disable():
        monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
        monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', False)

    dp = relay.build_dispatcher(SimpleNamespace(reload=disable))
    try:
        await dp.feed_update(configured, Update(update_id=1, message=message(text='/start')))
        Message.answer.assert_awaited_once_with(relay.PAUSED_MESSAGE, parse_mode=None)
        assert len(dp.message.handlers) == 2
        assert len(dp.callback_query.handlers) == 1
    finally:
        await dp.storage.close()


async def test_groups_are_ignored(configured):
    dp = relay.build_dispatcher(SimpleNamespace(reload=AsyncMock()))
    event = message(text='/start').model_copy(update={'chat': Chat(id=-100, type=ChatType.SUPERGROUP)})
    await dp.feed_update(configured, Update(update_id=1, message=event))
    Message.answer.assert_not_awaited()
    await dp.storage.close()


async def test_settings_failure_fails_closed(configured):
    dp = relay.build_dispatcher(SimpleNamespace(reload=AsyncMock(side_effect=RuntimeError('db unavailable'))))
    await dp.feed_update(configured, Update(update_id=1, message=message(text='/start')))
    Message.answer.assert_awaited_once_with(relay.UNAVAILABLE_MESSAGE, parse_mode=None)
    await dp.storage.close()


async def test_paid_update_failure_is_not_acknowledged(configured):
    dp = relay.build_dispatcher(SimpleNamespace(reload=AsyncMock(side_effect=RuntimeError('db unavailable'))))
    payment = SuccessfulPayment(
        currency='XTR',
        total_amount=20,
        invoice_payload='balance_42',
        telegram_payment_charge_id='telegram-charge',
        provider_payment_charge_id='provider-charge',
    )
    with pytest.raises(RuntimeError, match='db unavailable'):
        await dp.feed_update(configured, Update(update_id=1, message=message(successful_payment=payment)))
    Message.answer.assert_not_awaited()
    await dp.storage.close()


@pytest.mark.parametrize('enabled', [True, False])
async def test_stars_updates_go_to_payment_handlers_not_stub(configured, monkeypatch, enabled):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', enabled)
    paid, checkout = AsyncMock(), AsyncMock()
    paid.aiogram_flag = {}
    checkout.aiogram_flag = {}
    monkeypatch.setattr(relay, 'legacy_successful_payment', paid)
    monkeypatch.setattr(relay, 'legacy_pre_checkout', checkout)
    dp = relay.build_dispatcher(SimpleNamespace(reload=AsyncMock()))
    payment = SuccessfulPayment(
        currency='XTR',
        total_amount=20,
        invoice_payload='balance_42',
        telegram_payment_charge_id='telegram-charge',
        provider_payment_charge_id='provider-charge',
    )
    query = PreCheckoutQuery(
        id='checkout', from_user=message().from_user, currency='XTR', total_amount=20, invoice_payload='balance_42'
    )
    await dp.feed_update(configured, Update(update_id=1, message=message(successful_payment=payment)))
    await dp.feed_update(configured, Update(update_id=2, pre_checkout_query=query))
    paid.assert_awaited_once()
    checkout.assert_awaited_once()
    Message.answer.assert_not_awaited()
    Bot.send_message.assert_not_awaited()
    await dp.storage.close()


async def test_settings_loader_reads_only_without_runtime_apply_hooks(monkeypatch):
    # Include a setting whose normal apply hook would start an auto-backup task.
    monkeypatch.setattr(BotConfigurationService, '_is_env_override', lambda _key: False)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    monkeypatch.setattr(settings, 'BACKUP_AUTO_ENABLED', False)
    defaults = (settings.BOT_MIGRATION_ENABLED, settings.BACKUP_AUTO_ENABLED)
    rows = [
        SimpleNamespace(key='BOT_MIGRATION_ENABLED', value='true'),
        SimpleNamespace(key='BACKUP_AUTO_ENABLED', value='true'),
    ]
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.side_effect = [rows, []]
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(relay, 'AsyncSessionLocal', session)
    apply = MagicMock(side_effect=AssertionError('Runtime apply hook called'))
    monkeypatch.setattr(BotConfigurationService, '_apply_to_settings', apply)
    loader = relay.RelaySettingsLoader()
    await loader.reload()
    assert settings.BOT_MIGRATION_ENABLED and settings.BACKUP_AUTO_ENABLED
    await loader.reload()
    assert defaults == (settings.BOT_MIGRATION_ENABLED, settings.BACKUP_AUTO_ENABLED)
    db.commit.assert_not_awaited()
    apply.assert_not_called()


async def test_env_overrides_have_priority(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    monkeypatch.setattr(BotConfigurationService, '_is_env_override', lambda key: key == 'BOT_MIGRATION_ENABLED')
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        SimpleNamespace(key='BOT_MIGRATION_ENABLED', value='true')
    ]
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(relay, 'AsyncSessionLocal', session)
    await relay.RelaySettingsLoader().reload()
    assert not settings.BOT_MIGRATION_ENABLED


async def test_invalid_settings_do_not_publish_partial_changes(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    monkeypatch.setattr(BotConfigurationService, '_is_env_override', lambda _key: False)
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        SimpleNamespace(key='BOT_MIGRATION_ENABLED', value='true'),
        SimpleNamespace(key='BOT_MIGRATION_URL', value='https://not-telegram.example.com'),
    ]
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(relay, 'AsyncSessionLocal', session)
    with pytest.raises(ValueError):
        await relay.RelaySettingsLoader().reload()
    assert not settings.BOT_MIGRATION_ENABLED
    db.commit.assert_not_awaited()


async def test_legacy_payment_wrappers_supply_database_and_fsm(configured, monkeypatch):
    stars = ModuleType('app.handlers.stars_payments')
    stars.handle_successful_payment = AsyncMock()
    stars.handle_pre_checkout_query = AsyncMock()
    monkeypatch.setitem(sys.modules, 'app.handlers.stars_payments', stars)
    db, state = AsyncMock(), SimpleNamespace()
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(relay, 'AsyncSessionLocal', session)
    event = message(text='payment').as_(configured)
    await relay.legacy_successful_payment(event, state)
    stars.handle_successful_payment.assert_awaited_once_with(event, db=db, state=state)
    query = PreCheckoutQuery(
        id='checkout', from_user=message().from_user, currency='XTR', total_amount=20, invoice_payload='balance_42'
    )
    await relay.legacy_pre_checkout(query)
    stars.handle_pre_checkout_query.assert_awaited_once_with(query)


async def test_webhook_requires_secret_and_only_exposes_health_and_updates(configured):
    dp = relay.build_dispatcher(SimpleNamespace(reload=AsyncMock()))
    with pytest.raises(ValueError, match='SECRET_TOKEN'):
        relay.build_web_app(dp, configured, path='/legacy-webhook')
    app = relay.build_web_app(dp, configured, path='/legacy-webhook', secret='test-webhook-secret')
    assert {route.resource.canonical for route in app.router.routes()} == {'/health', '/legacy-webhook'}
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get('/health')
        assert response.status == 200
        assert (await response.json())['background_workers'] is False
        body = {'update_id': 1, 'message': message(text='/start').model_dump(mode='json', exclude_none=True)}
        response = await client.post('/legacy-webhook', json=body)
        assert response.status == 401
        Message.answer.assert_not_awaited()
        response = await client.post(
            '/legacy-webhook', json=body, headers={'X-Telegram-Bot-Api-Secret-Token': 'test-webhook-secret'}
        )
        assert response.status == 200
        Message.answer.assert_awaited_once()
        assert (await client.get('/cabinet/branding')).status == 404
    finally:
        await client.close()
        await dp.storage.close()


def test_import_does_not_load_full_bot_or_business_schedulers():
    code = """
import sys
import app.migration_bot
forbidden = ('main', 'app.bot', 'app.services.backup_service',
             'app.services.remnawave_sync_service', 'app.services.monitoring_service',
             'app.services.daily_subscription_service', 'app.services.reporting_service',
             'app.services.email_retry_service', 'app.handlers.stars_payments')
assert not set(forbidden).intersection(sys.modules)
"""
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and static local test code
        [sys.executable, '-c', code],
        env={**os.environ, 'BOT_TOKEN': '123456:test-token'},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_main_refuses_disabled_mode_without_changing_webhook(configured, monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    loader = SimpleNamespace(reload=AsyncMock())
    monkeypatch.setattr(relay, 'RelaySettingsLoader', lambda: loader)
    monkeypatch.setattr(relay, 'create_bot', lambda: configured)
    set_hook, delete_hook, close = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(Bot, 'set_webhook', set_hook)
    monkeypatch.setattr(Bot, 'delete_webhook', delete_hook)
    monkeypatch.setattr(configured.session, 'close', close)
    monkeypatch.setattr(relay, 'engine', SimpleNamespace(dispose=AsyncMock()))
    with pytest.raises(ValueError, match='включённом'):
        await relay.main()
    set_hook.assert_not_awaited()
    delete_hook.assert_not_awaited()
    close.assert_awaited_once()
    relay.engine.dispose.assert_awaited_once()


@pytest.mark.parametrize('mode', ['webhook', 'polling'])
async def test_main_runs_only_relay_transport_and_cleans_up(configured, monkeypatch, mode):
    monkeypatch.setattr(settings, 'BOT_RUN_MODE', mode)
    monkeypatch.setattr(settings, 'WEBHOOK_URL', 'https://old-hooks.example.com')
    monkeypatch.setattr(settings, 'WEBHOOK_PATH', '/old-telegram')
    monkeypatch.setattr(settings, 'WEBHOOK_SECRET_TOKEN', 'old-webhook-test-secret')
    loader = SimpleNamespace(reload=AsyncMock())
    dp = SimpleNamespace(storage=SimpleNamespace(close=AsyncMock()), start_polling=AsyncMock())
    runner = SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
    site = SimpleNamespace(start=AsyncMock())
    monkeypatch.setattr(relay, 'RelaySettingsLoader', lambda: loader)
    monkeypatch.setattr(relay, 'create_bot', lambda: configured)
    monkeypatch.setattr(relay, 'validate_relay', AsyncMock())
    monkeypatch.setattr(relay, 'build_dispatcher', lambda _loader: dp)
    app_builder = MagicMock()
    monkeypatch.setattr(relay, 'build_web_app', app_builder)
    monkeypatch.setattr(relay.web, 'AppRunner', lambda _app: runner)
    monkeypatch.setattr(relay.web, 'TCPSite', lambda _runner, _host, _port: site)
    monkeypatch.setattr(relay, 'wait_for_shutdown', AsyncMock())
    monkeypatch.setattr(Bot, 'set_webhook', AsyncMock())
    monkeypatch.setattr(Bot, 'delete_webhook', AsyncMock())
    monkeypatch.setattr(configured.session, 'close', AsyncMock())
    monkeypatch.setattr(relay, 'engine', SimpleNamespace(dispose=AsyncMock()))
    await relay.main()
    if mode == 'webhook':
        Bot.set_webhook.assert_awaited_once_with(
            url='https://old-hooks.example.com/old-telegram',
            secret_token='old-webhook-test-secret',
            allowed_updates=relay.ALLOWED_UPDATES,
            drop_pending_updates=False,
        )
        Bot.delete_webhook.assert_not_awaited()
        dp.start_polling.assert_not_awaited()
        relay.wait_for_shutdown.assert_awaited_once()
    else:
        Bot.set_webhook.assert_not_awaited()
        Bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
        dp.start_polling.assert_awaited_once_with(
            configured, allowed_updates=relay.ALLOWED_UPDATES, handle_as_tasks=False, close_bot_session=False
        )
    site.start.assert_awaited_once()
    runner.cleanup.assert_awaited_once()
    dp.storage.close.assert_awaited_once()
    configured.session.close.assert_awaited_once()
    relay.engine.dispose.assert_awaited_once()
