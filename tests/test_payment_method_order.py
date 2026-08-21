from aiogram.types import InlineKeyboardButton

from app.keyboards.inline import _apply_payment_name_overrides, _order_payment_method_rows


def _row(callback_data: str, text: str = 'Method') -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=callback_data)]


def test_preferred_payment_methods_are_ordered_for_regular_topup():
    rows = [
        _row('topup_stars'),
        _row('topup_rollypay'),
        _row('topup_platega_m2'),
        _row('topup_lava_card'),
        _row('topup_lava_sbp'),
        _row('topup_cispay_sbp'),
        _row('topup_support'),
    ]

    ordered = _order_payment_method_rows(rows)

    assert [row[0].callback_data for row in ordered] == [
        'topup_cispay_sbp',
        'topup_lava_card',
        'topup_lava_sbp',
        'topup_platega_m2',
        'topup_rollypay',
        'topup_stars',
        'topup_support',
    ]


def test_preferred_payment_methods_are_ordered_for_prefilled_amount():
    rows = [
        _row('topup_amount|stars|10000'),
        _row('topup_amount|platega_m2|10000'),
        _row('topup_amount|lava_card|10000'),
        _row('topup_amount|lava_sbp|10000'),
        _row('topup_amount|cispay_sbp|10000'),
        _row('topup_amount|support|10000'),
    ]

    ordered = _order_payment_method_rows(rows)

    assert [row[0].callback_data for row in ordered] == [
        'topup_amount|cispay_sbp|10000',
        'topup_amount|lava_card|10000',
        'topup_amount|lava_sbp|10000',
        'topup_amount|platega_m2|10000',
        'topup_amount|stars|10000',
        'topup_amount|support|10000',
    ]


def test_cispay_sbp_uses_requested_custom_emoji():
    from app.keyboards.inline import PAYMENT_METHOD_CUSTOM_EMOJI_IDS

    assert PAYMENT_METHOD_CUSTOM_EMOJI_IDS['cispay_sbp'] == '5265074015868822600'


def test_platega_sbp_is_always_marked_as_backup(monkeypatch):
    from app.services import payment_method_config_service

    monkeypatch.setattr(
        payment_method_config_service,
        'get_display_name_override',
        lambda _method: 'Custom SBP',
    )

    class Texts:
        @staticmethod
        def t(_key: str, _fallback: str) -> str:
            return 'СБП (запасной)'

    rows = [
        [
            InlineKeyboardButton(
                text='СБП',
                callback_data='topup_platega_m2',
                icon_custom_emoji_id='5222411706285725412',
            )
        ]
    ]

    _apply_payment_name_overrides(rows, Texts())

    assert rows[0][0].text == 'СБП (запасной)'
