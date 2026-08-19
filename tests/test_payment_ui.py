from app.handlers.balance.payment_ui import (
    AMOUNT_EMOJI_ID,
    INSTRUCTIONS_EMOJI_ID,
    PAY_BUTTON_EMOJI_ID,
    TOPUP_EMOJI_ID,
    build_payment_created_text,
    build_payment_keyboard,
    build_topup_prompt,
    format_rubles,
)


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
