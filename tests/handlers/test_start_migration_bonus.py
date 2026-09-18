from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, User

from app.config import settings
from app.handlers import start
from app.services.bot_migration_service import MigrationBonusResult
from app.services.registration_access_service import RegistrationAccessDecision, RegistrationAccessReason


class StopAfterMigration(Exception):
    """Stop before unrelated existing-account menu rendering."""


@pytest.fixture
def flow(monkeypatch):
    token = 'a' * 43
    bot = Bot('654321:test-token')
    event = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type='private'),
        from_user=User(id=42, is_bot=False, first_name='User'),
        text='/start move_' + token,
    ).as_(bot)
    answer = AsyncMock()
    monkeypatch.setattr(Message, 'answer', answer)
    monkeypatch.setattr(
        Bot, 'me', AsyncMock(return_value=User(id=654321, is_bot=True, first_name='Bot', username='new_service_bot'))
    )
    access_user = SimpleNamespace(id=11, status='active', language='ru')
    getter = AsyncMock(side_effect=[access_user, StopAfterMigration()])
    monkeypatch.setattr(start, 'get_user_by_telegram_id', getter)
    monkeypatch.setattr(start, 'get_pending_payload_from_redis', AsyncMock(return_value=None))
    monkeypatch.setattr(
        start,
        '_evaluate_telegram_registration_access',
        AsyncMock(return_value=RegistrationAccessDecision(True, RegistrationAccessReason.EXISTING_ACTIVE)),
    )
    campaign = AsyncMock(side_effect=AssertionError('Migration payload must not reach campaign lookup'))
    monkeypatch.setattr(start, 'get_campaign_by_start_parameter', campaign)
    db = AsyncMock()
    state = SimpleNamespace(get_data=AsyncMock(return_value={}), update_data=AsyncMock(), set_data=AsyncMock())
    claim = AsyncMock(return_value=MigrationBonusResult('credited', 7550))
    monkeypatch.setattr(start, 'claim_migration_bonus', claim)
    monkeypatch.setattr(
        settings,
        'BOT_MIGRATION_BONUS_SUCCESS_MESSAGE',
        '<tg-emoji emoji-id="5265039291058235695">🟢</tg-emoji> Вам начислено <b>{bonus} ₽</b>',
    )
    return event, db, state, claim, answer, token, campaign


async def test_start_credits_then_continues_without_campaign_or_referral_attribution(flow):
    event, db, state, claim, answer, token, campaign = flow
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    claim.assert_awaited_once_with(db, token, 42, 654321, 'new_service_bot')
    answer.assert_awaited_once_with(
        '<tg-emoji emoji-id="5265039291058235695">🟢</tg-emoji> Вам начислено <b>75.5 ₽</b>',
        parse_mode=ParseMode.HTML,
    )
    campaign.assert_not_awaited()


async def test_invalid_bonus_html_retries_delivery_without_crediting_twice(flow):
    event, db, state, claim, answer, token, campaign = flow
    answer.side_effect = [
        TelegramBadRequest(method=SendMessage(chat_id=42, text='test'), message="can't parse entities"),
        None,
    ]
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    claim.assert_awaited_once()
    assert answer.await_count == 2
    assert answer.await_args_list[1].args == ('🟢 Вам начислено 75.5 ₽',)
    assert answer.await_args_list[1].kwargs == {'parse_mode': None}
    state.update_data.assert_any_await(pending_migration_token=None)


async def test_unrelated_bonus_delivery_failure_is_not_retried(flow):
    event, db, state, claim, answer, token, campaign = flow
    answer.side_effect = TelegramBadRequest(method=SendMessage(chat_id=42, text='test'), message='chat not found')
    with pytest.raises(TelegramBadRequest, match='chat not found'):
        await start.cmd_start(event, state, db)
    claim.assert_awaited_once()
    answer.assert_awaited_once()


async def test_first_touch_campaign_cannot_hide_migration(flow):
    event, db, state, claim, answer, token, campaign = flow
    state.get_data.return_value = {'pending_start_payload': 'old_campaign', 'pending_payload_is_campaign': True}
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    claim.assert_awaited_once()
    campaign.assert_not_awaited()


async def test_saved_migration_token_survives_channel_gate_separately(flow):
    event, db, state, claim, answer, token, campaign = flow
    event = event.model_copy(update={'text': '/start'})
    state.get_data.return_value = {'pending_start_payload': 'old_campaign', 'pending_migration_token': token}
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    claim.assert_awaited_once()
    campaign.assert_not_awaited()
    state.update_data.assert_any_await(pending_migration_token=None)


async def test_pending_migration_payload_clears_real_redis_helper(monkeypatch, flow):
    event, db, state, claim, answer, token, campaign = flow
    state.get_data.return_value = {'pending_start_payload': 'move_' + token}
    delete = AsyncMock()
    monkeypatch.setattr(start, 'delete_pending_payload_from_redis', delete)
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    delete.assert_awaited_once_with(42)


async def test_failure_prompts_retry_without_success_or_menu(flow):
    event, db, state, claim, answer, token, campaign = flow
    claim.side_effect = RuntimeError('Ledger write failed')
    await start.cmd_start(event, state, db)
    assert 'Попробуйте' in answer.call_args.args[0]
    assert 'начислено' not in answer.call_args.args[0]
    state.update_data.assert_not_awaited()


@pytest.mark.parametrize('status', ['already_claimed', 'disabled', 'invalid'])
async def test_non_credit_status_does_not_send_credit_confirmation(flow, status):
    event, db, state, claim, answer, token, campaign = flow
    claim.return_value = MigrationBonusResult(status, 7550)
    with pytest.raises(StopAfterMigration):
        await start.cmd_start(event, state, db)
    assert 'Вам начислено' not in answer.call_args.args[0]
