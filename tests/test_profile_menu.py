from types import SimpleNamespace

from app.config import settings
from app.keyboards.inline import get_main_menu_keyboard, get_profile_keyboard


def _callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_personal_actions_are_grouped_under_profile(monkeypatch):
    monkeypatch.setattr(settings, 'REFERRAL_PROGRAM_ENABLED', True)
    monkeypatch.setattr(settings, 'LANGUAGE_SELECTION_ENABLED', True)

    main_callbacks = _callbacks(get_main_menu_keyboard(language='ru'))

    assert 'menu_profile' in main_callbacks
    assert 'menu_balance' not in main_callbacks
    assert 'menu_promocode' not in main_callbacks
    assert 'menu_referrals' not in main_callbacks
    assert 'menu_language' not in main_callbacks

    profile = get_profile_keyboard(language='ru', balance_kopeks=12_300)
    assert _callbacks(profile) == [
        'menu_balance',
        'menu_promocode',
        'menu_referrals',
        'menu_language',
        'back_to_menu',
    ]
    assert profile.inline_keyboard[1][1].text == '🤝 Реф. система'


def test_profile_hides_optional_actions_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'REFERRAL_PROGRAM_ENABLED', False)
    monkeypatch.setattr(settings, 'LANGUAGE_SELECTION_ENABLED', False)

    callbacks = _callbacks(get_profile_keyboard(language='ru'))

    assert callbacks == ['menu_balance', 'menu_promocode', 'back_to_menu']


def test_profile_is_near_the_top_for_every_subscription_state():
    without_subscription = get_main_menu_keyboard(
        language='ru',
        has_active_subscription=False,
        subscription_is_active=False,
    )
    assert without_subscription.inline_keyboard[0][0].callback_data == 'menu_profile'

    subscription = SimpleNamespace(
        subscription_url=None,
        subscription_crypto_link=None,
        is_trial=False,
        traffic_limit_gb=0,
    )
    with_subscription = get_main_menu_keyboard(
        language='ru',
        has_active_subscription=True,
        subscription_is_active=True,
        subscription=subscription,
    )
    assert with_subscription.inline_keyboard[1][0].callback_data == 'menu_profile'


def test_buy_and_trial_use_separate_rows_with_buy_first(monkeypatch):
    monkeypatch.setattr(settings, 'TRIAL_DURATION_DAYS', 3)
    monkeypatch.setattr(settings, 'TRIAL_DISABLED_FOR', 'none')

    markup = get_main_menu_keyboard(
        language='ru',
        has_had_paid_subscription=False,
        has_active_subscription=False,
        subscription_is_active=False,
        trial_already_used=False,
    )
    rows = [[button.callback_data for button in row] for row in markup.inline_keyboard]

    buy_row = rows.index(['menu_buy'])
    trial_row = rows.index(['menu_trial'])
    assert buy_row < trial_row
