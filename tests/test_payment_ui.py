from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.handlers.balance.payment_ui import (
    AMOUNT_EMOJI_ID,
    INSTRUCTIONS_EMOJI_ID,
    PAY_BUTTON_EMOJI_ID,
    TOPUP_EMOJI_ID,
    build_payment_created_text,
    build_payment_keyboard,
    build_topup_prompt,
    format_rubles,
    get_common_payment_text,
)
from app.utils.custom_emoji_buttons import apply_custom_emoji_icons


def test_format_rubles_is_consistent() -> None:
    assert format_rubles(10_000) == '100'
    assert format_rubles(12_345, decimals=True) == '123.45'
    assert format_rubles(10_000_000) == '100 000'


def test_standard_topup_prompt_uses_custom_emoji_and_escaped_name() -> None:
    text = build_topup_prompt('ru', 'CisPay <SBP>', 10_000, 10_000_000)

    assert f'emoji-id="{TOPUP_EMOJI_ID}"' in text
    assert 'CisPay &lt;SBP&gt;' in text
    assert 'от <b>100 ₽</b> до <b>100 000 ₽</b>' in text


def test_standard_invoice_has_shared_structure() -> None:
    text = build_payment_created_text('ru', 'CisPay', 12_345)

    assert f'emoji-id="{TOPUP_EMOJI_ID}"' in text
    assert f'emoji-id="{AMOUNT_EMOJI_ID}"' in text
    assert f'emoji-id="{INSTRUCTIONS_EMOJI_ID}"' in text
    assert 'Сумма: <b>123.45 ₽</b>' in text
    assert 'Нажмите кнопку «Оплатить»' in text


def test_standard_pay_button_uses_custom_emoji() -> None:
    keyboard = build_payment_keyboard('ru', 'https://pay.example/invoice', 10_000)
    pay_button = keyboard.inline_keyboard[0][0]

    assert pay_button.url == 'https://pay.example/invoice'
    assert pay_button.icon_custom_emoji_id == PAY_BUTTON_EMOJI_ID
    assert pay_button.text == 'Оплатить 100 ₽'


def test_payment_keyboard_supports_multiple_provider_actions() -> None:
    keyboard = build_payment_keyboard(
        'ru',
        None,
        10_000,
        payment_actions=(
            ('Оплатить через СБП', 'https://example.com/sbp'),
            ('Оплатить картой', 'https://example.com/card'),
        ),
    )

    assert [row[0].url for row in keyboard.inline_keyboard[:-1]] == [
        'https://example.com/sbp',
        'https://example.com/card',
    ]
    assert all(row[0].icon_custom_emoji_id == PAY_BUTTON_EMOJI_ID for row in keyboard.inline_keyboard[:-1])


def test_legacy_provider_keys_resolve_to_one_shared_template() -> None:
    aura = get_common_payment_text('AURAPAY_PAYMENT_CREATED', 'ru')
    cispay = get_common_payment_text('CISPAY_PAYMENT_CREATED', 'ru')

    assert aura == cispay
    assert f'emoji-id="{TOPUP_EMOJI_ID}"' in aura
    assert '{name}' in aura
    assert '{amount}' in aura


def test_non_brand_language_keeps_its_original_provider_copy() -> None:
    assert get_common_payment_text('CISPAY_PAYMENT_CREATED', 'zh') is None


def test_legacy_provider_buttons_receive_shared_custom_icons() -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 CisPay', callback_data='topup_cispay')],
            [InlineKeyboardButton(text='💳 Оплатить 100 ₽', url='https://pay.example')],
        ]
    )

    decorated = apply_custom_emoji_icons(markup)

    assert decorated.inline_keyboard[0][0].icon_custom_emoji_id == TOPUP_EMOJI_ID
    assert decorated.inline_keyboard[1][0].icon_custom_emoji_id == PAY_BUTTON_EMOJI_ID
    assert decorated.inline_keyboard[0][0].text == 'CisPay'
    assert decorated.inline_keyboard[1][0].text == 'Оплатить 100 ₽'
