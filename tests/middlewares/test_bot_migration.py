from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User

from app.config import settings
from app.middlewares.bot_migration import BotMigrationMiddleware


def message(**kwargs):
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type=ChatType.PRIVATE),
        from_user=User(id=42, is_bot=False, first_name='User'),
        text='/start',
        **kwargs,
    ).as_(Bot('123456:test-token'))


@pytest.fixture
def migration(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', True)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/new_service_bot?start=migration')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_MESSAGE', 'Переезд <без HTML> & бонусов')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BUTTON_TEXT', 'Перейти')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', False)
    monkeypatch.setattr(
        Bot, 'me', AsyncMock(return_value=User(id=123456, is_bot=True, first_name='Old', username='old_bot'))
    )
    monkeypatch.setattr(type(settings), 'is_admin', lambda _self, user_id: False)
    replies = AsyncMock()
    answers = AsyncMock()
    sends = AsyncMock()
    monkeypatch.setattr(Message, 'answer', replies)
    monkeypatch.setattr(CallbackQuery, 'answer', answers)
    monkeypatch.setattr(Bot, 'send_message', sends)
    return replies, answers, sends


async def test_message_replaced_with_plain_text_and_url_button(migration):
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, message(), {})
    handler.assert_not_awaited()
    replies, _, _ = migration
    replies.assert_awaited_once()
    assert replies.call_args.args == (settings.BOT_MIGRATION_MESSAGE,)
    assert replies.call_args.kwargs['parse_mode'] is None
    button = replies.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == 'Перейти'
    assert button.url == settings.BOT_MIGRATION_URL


@pytest.mark.parametrize('with_message', [True, False])
async def test_old_callback_and_inline_callback_get_stub(migration, with_message):
    bot = Bot('123456:test-token')
    event = CallbackQuery(
        id='old-button',
        from_user=message().from_user,
        chat_instance='chat',
        data='obsolete_unknown_button',
        message=message() if with_message else None,
        inline_message_id=None if with_message else 'inline-id',
    ).as_(bot)
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, event, {})
    handler.assert_not_awaited()
    _, answers, sends = migration
    answers.assert_awaited_once()
    sends.assert_awaited_once()
    assert sends.call_args.args[0] == 42
    assert sends.call_args.kwargs['reply_markup'].inline_keyboard[0][0].url == settings.BOT_MIGRATION_URL


async def test_stale_callback_still_sends_url(migration):
    _, answers, sends = migration
    answers.side_effect = TelegramBadRequest(method=None, message='query is too old')
    event = CallbackQuery(
        id='stale', from_user=message().from_user, chat_instance='chat', data='menu_balance', message=message()
    ).as_(Bot('123456:test-token'))
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, event, {})
    sends.assert_awaited_once()
    handler.assert_not_awaited()


@pytest.mark.parametrize('case', ['disabled', 'admin', 'group', 'payment', 'pre_checkout', 'bot'])
async def test_exempt_events_continue_normally(monkeypatch, migration, case):
    event = message()
    if case == 'disabled':
        monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    elif case == 'admin':
        monkeypatch.setattr(type(settings), 'is_admin', lambda _self, user_id: True)
    elif case == 'group':
        event = event.model_copy(update={'chat': Chat(id=-10042, type=ChatType.SUPERGROUP)})
    elif case == 'bot':
        event = event.model_copy(update={'from_user': User(id=42, is_bot=True, first_name='Bot')})
    elif case == 'payment':
        event = message(
            successful_payment=SuccessfulPayment(
                currency='XTR',
                total_amount=50,
                invoice_payload='existing_invoice',
                telegram_payment_charge_id='tg',
                provider_payment_charge_id='provider',
            )
        )
    elif case == 'pre_checkout':
        event = PreCheckoutQuery(
            id='checkout',
            from_user=message().from_user,
            currency='XTR',
            total_amount=50,
            invoice_payload='existing_invoice',
        )
    handler = AsyncMock(return_value='handled')
    assert await BotMigrationMiddleware()(handler, event, {}) == 'handled'
    handler.assert_awaited_once_with(event, {})
    for response in migration:
        response.assert_not_awaited()


async def test_unreachable_user_does_not_fall_through(migration):
    replies, _, _ = migration
    replies.side_effect = TelegramForbiddenError(method=None, message='bot was blocked by the user')
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, message(), {})
    handler.assert_not_awaited()


async def test_outer_middleware_intercepts_unmatched_updates(migration):
    dp = Dispatcher()
    dp.message.outer_middleware(BotMigrationMiddleware())
    dp.callback_query.outer_middleware(BotMigrationMiddleware())
    bot = Bot('123456:test-token')
    await dp.feed_update(bot, Update(update_id=1, message=message()))
    event = CallbackQuery(id='unknown', from_user=message().from_user, chat_instance='chat', data='unknown')
    await dp.feed_update(bot, Update(update_id=2, callback_query=event))
    replies, answers, sends = migration
    replies.assert_awaited_once()
    answers.assert_awaited_once()
    sends.assert_awaited_once()


async def test_outer_middleware_stops_registered_handler_and_can_be_disabled(monkeypatch, migration):
    dp = Dispatcher()
    dp.message.outer_middleware(BotMigrationMiddleware())
    handled = AsyncMock()

    @dp.message()
    async def normal_handler(event: Message):
        await handled(event)

    bot = Bot('123456:test-token')
    await dp.feed_update(bot, Update(update_id=1, message=message()))
    handled.assert_not_awaited()
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    await dp.feed_update(bot, Update(update_id=2, message=message()))
    handled.assert_awaited_once()


async def test_active_fsm_is_not_consumed_by_migration(migration):
    from aiogram.filters import StateFilter

    dp = Dispatcher()
    dp.message.outer_middleware(BotMigrationMiddleware())
    bot = Bot('123456:test-token')
    context = dp.fsm.get_context(bot=bot, chat_id=42, user_id=42)
    await context.set_state('checkout:waiting')
    handled = AsyncMock()

    @dp.message(StateFilter('checkout:waiting'))
    async def checkout_handler(event: Message):
        await handled(event)

    await dp.feed_update(bot, Update(update_id=1, message=message()))
    handled.assert_not_awaited()
    assert await context.get_state() == 'checkout:waiting'
    migration[0].assert_awaited_once()


async def test_target_bot_remains_working_with_shared_migration_settings(monkeypatch, migration):
    monkeypatch.setattr(
        Bot, 'me', AsyncMock(return_value=User(id=654321, is_bot=True, first_name='New', username='new_service_bot'))
    )
    handler = AsyncMock(return_value='normal')
    assert await BotMigrationMiddleware()(handler, message(), {}) == 'normal'
    handler.assert_awaited_once()
    migration[0].assert_not_awaited()


async def test_target_bot_saves_bonus_separately_from_campaign_for_channel_gate(monkeypatch, migration):
    from types import SimpleNamespace

    monkeypatch.setattr(
        Bot, 'me', AsyncMock(return_value=User(id=654321, is_bot=True, first_name='New', username='new_service_bot'))
    )
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', True)
    state = SimpleNamespace(update_data=AsyncMock())
    event = message().model_copy(update={'text': '/start move_' + 'a' * 43})
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, event, {'state': state})
    state.update_data.assert_awaited_once_with(pending_migration_token='a' * 43)
    handler.assert_awaited_once()


@pytest.mark.parametrize('amount', [7550, 0])
async def test_personal_link_renders_actual_promised_amount(monkeypatch, migration, amount):
    from types import SimpleNamespace

    from app.services.bot_migration_service import MigrationLink

    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', True)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_MESSAGE', 'Переход: {bonus} ₽')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BUTTON_TEXT', 'Получить {bonus} ₽')
    db = SimpleNamespace()
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr('app.middlewares.bot_migration.AsyncSessionLocal', lambda: context)
    url = 'https://t.me/new_service_bot?start=move_' + 'a' * 43 if amount else settings.BOT_MIGRATION_URL
    issue = AsyncMock(return_value=MigrationLink(url, amount))
    monkeypatch.setattr('app.middlewares.bot_migration.issue_migration_link', issue)
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, message(), {})
    issue.assert_awaited_once_with(db, 42, 123456)
    handler.assert_not_awaited()
    replies = migration[0]
    expected = 'Переход: 75.5 ₽' if amount else settings.BOT_MIGRATION_NO_BONUS_MESSAGE
    assert replies.call_args.args[0] == expected
    button = replies.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.url == url
    assert button.text == ('Получить 75.5 ₽' if amount else settings.BOT_MIGRATION_NO_BONUS_BUTTON_TEXT)


async def test_issue_failure_never_sends_generic_link_promising_bonus(monkeypatch, migration):
    context = AsyncMock()
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', True)
    monkeypatch.setattr('app.middlewares.bot_migration.AsyncSessionLocal', lambda: context)
    monkeypatch.setattr(
        'app.middlewares.bot_migration.issue_migration_link', AsyncMock(side_effect=RuntimeError('db down'))
    )
    handler = AsyncMock()
    await BotMigrationMiddleware()(handler, message(), {})
    handler.assert_not_awaited()
    migration[0].assert_not_awaited()
    migration[2].assert_awaited_once()
    assert 'Попробуйте' in migration[2].call_args.args[1]
    assert 'reply_markup' not in migration[2].call_args.kwargs
