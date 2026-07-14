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
        ('📦 Тариф', 'instant_switch', 'tariff'),
        ('📈 Докупить трафик', 'buy_traffic', 'buy_traffic'),
        ('✅ Включить', 'autopay_enable', 'enable'),
        ('❌ Выключить', 'autopay_disable', 'disable'),
        ('⚙️ Настроить дни', 'autopay_set_days', 'configure'),
        ('📅 Период продления', 'autopay_set_period', 'renewal_period'),
        ('🔧 Управление устройствами', 'subscription_manage_devices', 'manage_devices'),
        ('🔄 Перевыпустить подписку', 'subscription_revoke', 'revoke_subscription'),
        ('⚙️ Настройки', 'subscription_settings', 'configure'),
        ('💰 Баланс: 100 ₽', 'menu_balance', 'balance'),
        ('🎟️ Промокод', 'menu_promocode', 'promocode'),
        ('🤝 Реф. система', 'menu_referrals', 'referral_system'),
        ('🌐 Язык', 'menu_language', 'language'),
        ('📊 История операций', 'balance_history', 'balance_history'),
        ('💳 Пополнить', 'balance_topup', 'balance_topup'),
        ('📝 Создать приглашение', 'referral_create_invite', 'create_invite'),
        ('📱 Показать QR код', 'referral_show_qr', 'show_qr'),
        ('👥 Список рефералов', 'referral_list', 'referral_list'),
        ('📊 Аналитика', 'referral_analytics', 'referral_analytics'),
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


def test_ticket_creation_cancel_uses_its_specific_icon():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button('❌ Отменить создание тикета', callback_data='cancel_ticket_creation')],
            [_button('❌ Отмена', callback_data='some_other_cancel')],
        ]
    )

    specific, generic = [row[0] for row in apply_custom_emoji_icons(markup).inline_keyboard]
    assert specific.icon_custom_emoji_id == CUSTOM_EMOJI_IDS['cancel_ticket_creation']
    assert generic.icon_custom_emoji_id == CUSTOM_EMOJI_IDS['cancel']
