from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.handlers import referral
from app.keyboards.inline import get_referral_keyboard
from app.utils.message_patch import is_qr_message


class FakeTexts:
    BACK = 'Назад'

    def t(self, _key: str, default: str):
        return default

    def format_price(self, amount: int):
        return f'{amount / 100:g} ₽'


def test_referral_keyboard_no_longer_contains_separate_qr_button():
    keyboard = get_referral_keyboard('ru')

    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    assert 'referral_show_qr' not in callbacks
    assert 'referral_analytics' in callbacks


def test_referral_program_caption_marks_photo_as_qr():
    message = SimpleNamespace(caption='🔎 Реферальная программа\n\nТекст')

    assert is_qr_message(message) is True


def test_referral_qr_is_cached_by_user_and_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    first = referral._get_referral_qr_path(42, 'https://t.me/example_bot?start=ref-code')
    second = referral._get_referral_qr_path(42, 'https://t.me/example_bot?start=ref-code')

    assert first == second
    assert first.is_file()
    assert first.parent == Path('data') / 'referral_qr'


@pytest.mark.asyncio
async def test_referral_main_uses_qr_copyable_links_and_retention_reward(monkeypatch: pytest.MonkeyPatch):
    callback = SimpleNamespace(
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='example_bot'))),
        answer=AsyncMock(),
    )
    db_user = SimpleNamespace(id=42, language='ru', referral_code='ref-code')
    rendered = AsyncMock()
    summary_loader = AsyncMock()

    monkeypatch.setattr(referral, 'get_texts', lambda _language: FakeTexts())
    monkeypatch.setattr(referral, 'get_referral_keyboard', lambda _language: Mock())
    monkeypatch.setattr(referral, '_show_referral_screen_with_qr', rendered)
    monkeypatch.setattr(referral, '_get_referral_qr_path', lambda *_args: Path('referral.png'))
    monkeypatch.setattr(referral, 'get_user_referral_summary', summary_loader)
    monkeypatch.setattr(
        referral,
        'settings',
        SimpleNamespace(
            is_referral_program_enabled=lambda: True,
            is_referral_levels_scheme=lambda: False,
            get_bot_referral_link=lambda _code, _username: (
                'https://t.me/example_bot?start=ref-code&source=test'
            ),
            get_cabinet_referral_link=lambda _code: 'https://cabinet.example/ref=ref-code&source=test',
            REFERRAL_FIRST_TOPUP_BONUS_KOPEKS=0,
            REFERRAL_INVITER_BONUS_KOPEKS=0,
            REFERRAL_MAX_COMMISSION_PAYMENTS=0,
            REFERRAL_RETENTION_REWARD_ENABLED=True,
            REFERRAL_RETENTION_REWARD_KOPEKS=5_000,
            REFERRAL_RETENTION_DAYS=7,
        ),
    )

    await referral.show_referral_info(callback, db_user, AsyncMock())

    summary_loader.assert_not_awaited()
    caption = rendered.await_args.kwargs['caption']
    assert 'Ваша статистика' not in caption
    assert 'не блокирует бота в течение 7 дней' in caption
    assert '<code>https://t.me/example_bot?start=ref-code&amp;source=test</code>' in caption
    assert '<code>https://cabinet.example/ref=ref-code&amp;source=test</code>' in caption
    assert '<code>ref-code</code>' in caption
    assert rendered.await_args.kwargs['qr_path'] == Path('referral.png')


@pytest.mark.asyncio
async def test_referral_analytics_contains_moved_summary(monkeypatch: pytest.MonkeyPatch):
    callback = SimpleNamespace(answer=AsyncMock())
    db_user = SimpleNamespace(id=42, language='ru')
    rendered = AsyncMock()

    monkeypatch.setattr(referral, 'get_texts', lambda _language: FakeTexts())
    monkeypatch.setattr(
        referral,
        'get_user_referral_summary',
        AsyncMock(
            return_value={
                'invited_count': 3,
                'paid_referrals_count': 2,
                'active_referrals_count': 1,
                'conversion_rate': 66.7,
                'total_earned_kopeks': 12_300,
                'month_earned_kopeks': 4_500,
            }
        ),
    )
    monkeypatch.setattr(
        referral,
        'get_referral_analytics',
        AsyncMock(
            return_value={
                'earnings_by_period': {
                    'today': 100,
                    'week': 200,
                    'month': 300,
                    'quarter': 400,
                }
            }
        ),
    )
    monkeypatch.setattr(referral, 'edit_or_answer_photo', rendered)

    await referral.show_referral_analytics(callback, db_user, AsyncMock())

    text = rendered.await_args.args[1]
    assert 'Ваша статистика' in text
    assert 'Приглашено пользователей: <b>3</b>' in text
    assert 'Доходы по периодам' in text
