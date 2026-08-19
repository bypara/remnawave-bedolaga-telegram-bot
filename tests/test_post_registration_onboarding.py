from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.handlers import menu, start
from app.keyboards.inline import get_post_registration_keyboard
from app.localization.texts import get_texts


def _trial_user(**overrides):
    values = {
        'subscriptions': [],
        'auth_type': 'telegram',
        'has_had_paid_subscription': False,
        'is_trial_already_used': lambda: False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_post_registration_keyboard_opens_trial_details_before_activation():
    keyboard = get_post_registration_keyboard('ru')

    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        ['menu_trial'],
        ['post_registration_explore'],
    ]
    assert keyboard.inline_keyboard[0][0].text == get_texts('ru').t(
        'POST_REGISTRATION_TRIAL_BUTTON',
        'Попробовать тестовую подписку',
    )
    assert keyboard.inline_keyboard[0][0].style == 'danger'
    assert keyboard.inline_keyboard[1][0].text == 'Я пока тут осмотрюсь'


def test_post_registration_trial_offer_respects_eligibility(monkeypatch):
    monkeypatch.setattr(settings, 'TRIAL_DURATION_DAYS', 3)
    monkeypatch.setattr(settings, 'TRIAL_DISABLED_FOR', 'none')

    assert start._can_offer_post_registration_trial(_trial_user()) is True
    assert start._can_offer_post_registration_trial(_trial_user(has_had_paid_subscription=True)) is False
    assert start._can_offer_post_registration_trial(
        _trial_user(is_trial_already_used=lambda: True)
    ) is False
    assert start._can_offer_post_registration_trial(
        _trial_user(subscriptions=[SimpleNamespace(is_active=True)])
    ) is False

    monkeypatch.setattr(settings, 'TRIAL_DURATION_DAYS', 0)
    assert start._can_offer_post_registration_trial(_trial_user()) is False


@pytest.mark.asyncio
async def test_language_selection_is_removed_without_confirmation_message(monkeypatch):
    callback = AsyncMock()
    callback.data = 'language_select:ru'
    callback.from_user.id = 42
    callback.message.delete = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()

    state = AsyncMock()
    state.get_data.return_value = {}
    continue_registration = AsyncMock()

    monkeypatch.setattr(settings, 'AVAILABLE_LANGUAGES', 'ru,en')
    monkeypatch.setattr(start, '_continue_registration_after_language', continue_registration)

    await start.process_language_selection(callback, state, AsyncMock())

    callback.message.delete.assert_awaited_once()
    callback.message.answer.assert_not_awaited()
    callback.message.edit_reply_markup.assert_not_awaited()
    continue_registration.assert_awaited_once()


@pytest.mark.asyncio
async def test_registration_continues_without_separate_legal_acceptance(monkeypatch):
    message = AsyncMock()
    message.from_user.id = 42
    state = AsyncMock()
    state.get_data.return_value = {'language': 'ru'}
    complete_registration = AsyncMock()

    monkeypatch.setattr(settings, 'SKIP_REFERRAL_CODE', True)
    monkeypatch.setattr(start, 'complete_registration', complete_registration)

    await start._continue_registration_after_language(
        message=message,
        callback=None,
        state=state,
        db=AsyncMock(),
    )

    complete_registration.assert_awaited_once()
    state.set_state.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_back_to_menu_cannot_bypass_required_post_registration_choice():
    callback = AsyncMock()
    callback.message.message_id = 101
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.get_data.return_value = {
        'post_registration_choice_pending': True,
        'post_registration_offer_text': 'Offer',
    }
    user = SimpleNamespace(language='ru')

    await menu.handle_back_to_menu(callback, state, user, AsyncMock())

    callback.message.edit_text.assert_awaited_once()
    keyboard = callback.message.edit_text.await_args.kwargs['reply_markup']
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        ['menu_trial'],
        ['post_registration_explore'],
    ]
    callback.answer.assert_awaited_once_with(
        'Сначала выберите один из двух вариантов ниже.',
        show_alert=True,
    )
    state.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_explore_choice_opens_main_menu_with_legal_warning(monkeypatch):
    callback = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    user = SimpleNamespace(language='ru')
    warning = 'Continue = consent'
    show_main_menu = AsyncMock()

    monkeypatch.setattr(menu, 'build_browsing_consent_warning', AsyncMock(return_value=warning))
    monkeypatch.setattr(menu, 'show_main_menu', show_main_menu)

    await menu.handle_post_registration_explore(callback, state, user, AsyncMock())

    state.clear.assert_awaited_once()
    show_main_menu.assert_awaited_once()
    assert show_main_menu.await_args.kwargs['notice'] == warning
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_start_replaces_offer_and_keeps_choice_required():
    message = AsyncMock()
    message.chat.id = 42
    message.delete = AsyncMock()
    sent_message = SimpleNamespace(message_id=202)
    message.bot.delete_message = AsyncMock()
    message.bot.send_message = AsyncMock(return_value=sent_message)
    state = AsyncMock()
    user = SimpleNamespace(language='ru')

    await start._repeat_required_post_registration_choice(
        message,
        state,
        user,
        get_texts('ru'),
        {
            'post_registration_offer_message_id': 101,
            'post_registration_offer_text': 'Offer',
        },
    )

    message.bot.delete_message.assert_awaited_once_with(42, 101)
    message.delete.assert_awaited_once()
    assert message.bot.send_message.await_args.kwargs['text'].startswith(
        'Сначала выберите один из двух вариантов ниже.\n\n'
    )
    state.update_data.assert_awaited_once_with(
        post_registration_choice_pending=True,
        post_registration_offer_message_id=202,
        post_registration_offer_text='Offer',
    )
