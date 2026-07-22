from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.keyboards.inline import get_change_devices_keyboard, get_confirm_change_devices_keyboard
from app.localization.texts import get_texts


def test_device_change_copy_uses_requested_custom_emojis_in_both_languages():
    expected = {
        'CHANGE_DEVICES_PROMPT': ('5341715473882955310', '5422439311196834318'),
        'DEVICE_CHANGE_INSUFFICIENT_FUNDS_MESSAGE': ('5447644880824181073',),
        'DEVICE_CHANGE_CONFIRMATION': ('5341715473882955310',),
        'DEVICE_CHANGE_INCREASE_SUCCESS': ('5206607081334906820',),
        'DEVICE_CHANGE_INCREASE_RESULT_LINE': ('5397916757333654639',),
    }

    for language in ('ru', 'en'):
        texts = get_texts(language)
        for key, emoji_ids in expected.items():
            value = texts.t(key)
            for emoji_id in emoji_ids:
                assert f'emoji-id="{emoji_id}"' in value


def test_device_change_buttons_use_requested_custom_emojis():
    tariff = SimpleNamespace(device_price_kopeks=30_00, device_limit=1, max_device_limit=4)
    keyboard = get_change_devices_keyboard(
        1,
        'ru',
        datetime.now(UTC) + timedelta(days=30),
        tariff=tariff,
    )

    current_button = keyboard.inline_keyboard[0][0]
    increase_buttons = [row[0] for row in keyboard.inline_keyboard[1:-1]]
    confirm_button = get_confirm_change_devices_keyboard(2, 30_00, 'ru').inline_keyboard[0][0]

    assert current_button.icon_custom_emoji_id == '5206607081334906820'
    assert increase_buttons
    assert all(button.icon_custom_emoji_id == '5397916757333654639' for button in increase_buttons)
    assert confirm_button.icon_custom_emoji_id == '5206607081334906820'
