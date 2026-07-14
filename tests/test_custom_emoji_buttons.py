from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.custom_emoji_buttons import CUSTOM_EMOJI_IDS, apply_custom_emoji_icons


def _button(text: str, callback_data: str | None = None, url: str | None = None):
    return InlineKeyboardButton(text=text, callback_data=callback_data, url=url)


def test_requested_custom_emoji_icons_are_applied_by_button_action():
    cases = [
        ('💎 Купить подписку', 'menu_buy', 'buy_main'),
        ('🧪 Тестовая подписка', 'menu_trial', 'trial'),
        ('🎫 Создать тикет', 'create_ticket', 'create_ticket'),
        ('📋 Мои тикеты', 'my_tickets', 'my_tickets'),
        ('📋 Правила сервиса', 'menu_rules', 'rules'),
        ('🎁 Активировать', 'trial_activate', 'activate'),
        ('🔗 Подключиться', 'subscription_connect', 'connect'),
        ('💎 Купить подписку', 'subscription_upgrade', 'buy_from_trial'),
        ('✅ Подтвердить покупку', 'subscription_confirm', 'confirm_purchase'),
        ('📱 Моя подписка', 'menu_subscription', 'my_subscription'),
        ('⏰ Продлить подписку', 'subscription_extend', 'extend_subscription'),
        ('💳 Автоплатёж', 'subscription_autopay', 'autopay'),
        ('⚙️ Настройки', 'subscription_settings', 'subscription_settings'),
        ('📦 Тариф', 'instant_switch', 'tariff'),
        ('📈 Докупить трафик', 'buy_traffic', 'buy_traffic'),
    ]
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[_button(text, callback_data=callback)] for text, callback, _ in cases]
    )

    decorated = apply_custom_emoji_icons(markup)

    for row, (original_text, _, icon_name) in zip(decorated.inline_keyboard, cases, strict=True):
        button = row[0]
        assert button.text != original_text
        assert button.text == original_text.split(' ', 1)[1]
        assert button.icon_custom_emoji_id == CUSTOM_EMOJI_IDS[icon_name]


def test_url_contact_and_all_back_cancel_buttons_are_decorated():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button('💬 Связаться с поддержкой', url='https://t.me/support')],
            [_button('⬅️ Назад', callback_data='anything')],
            [_button('🏠 В главное меню', callback_data='back_to_menu')],
            [_button('❌ Отмена', callback_data='anything_else')],
        ]
    )

    contact, back, home, cancel = [row[0] for row in apply_custom_emoji_icons(markup).inline_keyboard]
    assert (contact.text, contact.icon_custom_emoji_id) == (
        'Связаться с поддержкой',
        CUSTOM_EMOJI_IDS['contact_support'],
    )
    assert (back.text, back.icon_custom_emoji_id) == ('Назад', CUSTOM_EMOJI_IDS['back'])
    assert (home.text, home.icon_custom_emoji_id) == ('В главное меню', CUSTOM_EMOJI_IDS['back'])
    assert (cancel.text, cancel.icon_custom_emoji_id) == ('Отмена', CUSTOM_EMOJI_IDS['cancel'])


def test_existing_context_specific_icon_is_preserved():
    main_menu_subscription_icon = '5319272710688226013'
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='Подписка',
                    callback_data='menu_subscription',
                    icon_custom_emoji_id=main_menu_subscription_icon,
                )
            ]
        ]
    )

    decorated = apply_custom_emoji_icons(markup)

    assert decorated.inline_keyboard[0][0].icon_custom_emoji_id == main_menu_subscription_icon
