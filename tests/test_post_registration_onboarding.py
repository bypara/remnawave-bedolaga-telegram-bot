from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.handlers import start
from app.keyboards.inline import get_post_registration_keyboard


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
        ['back_to_menu'],
    ]
    assert keyboard.inline_keyboard[0][0].text == 'Попробовать тестовую подписку'
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
