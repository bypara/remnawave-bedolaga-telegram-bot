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
        ('🟢 Закрытые тикеты', 'my_tickets_closed', 'closed_tickets'),
        ('🛡️ Политика конфиденциальности', 'menu_privacy_policy', 'privacy_policy'),
        ('📄 Оферта', 'menu_public_offer', 'public_offer'),
        ('📋 Правила сервиса', 'menu_rules', 'rules'),
        ('🎁 Активировать', 'trial_activate', 'activate'),
        ('🔗 Подключиться', 'subscription_connect', 'connect'),
        ('💎 Купить подписку', 'subscription_upgrade', 'buy_from_trial'),
        ('✅ Подтвердить покупку', 'subscription_confirm', 'confirm_purchase'),
        ('✅ Подтвердить покупку', 'tariff_confirm:1:14', 'confirm_purchase'),
        ('✅ Подтвердить покупку', 'daily_tariff_confirm:1', 'confirm_purchase'),
        ('✅ Подтвердить покупку', 'custom_confirm:1', 'confirm_purchase'),
        ('✅ Подтвердить продление', 'tariff_ext_confirm:1:1:14', 'confirm_purchase'),
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
        ('💸 Запросить вывод', 'referral_withdrawal', 'referral_withdrawal'),
        ('📝 Оформить заявку', 'referral_withdrawal_start', 'referral_withdrawal_request'),
        ('✅ Подтвердить', 'referral_withdrawal_confirm', 'referral_withdrawal_confirm'),
        ('✅ Я подписался', 'sub_channel_check', 'channel_check'),
        ('🎁 Получить скидку', 'claim_discount_42', 'claim_discount'),
        ('✅ Подтвердить переключение', 'instant_sw_confirm:2', 'confirm_switch'),
        ('✅ Подтвердить переключение', 'tariff_sw_confirm:2:30', 'confirm_switch'),
        ('✅ Подтвердить переключение', 'daily_tariff_switch_confirm:2', 'confirm_switch'),
        ('⚙️ Минимум', 'sm:1', 'my_subscription'),
        ('🔗 Ссылка подключения', 'sl:1', 'connect'),
        ('🔄 Продлить', 'se:1', 'extend_subscription'),
        ('📊 Трафик', 'st:1', 'buy_traffic'),
        ('📱 Устройства', 'sd:1', 'manage_devices'),
        ('🗑 Удалить подписку', 'sub_del:1', 'disable'),
        ('🔄 Перевыпустить', 'sr:1', 'revoke_subscription'),
        ('➕ Докупить устройства', 'change_devices_menu:1', 'configure'),
        ('📱 Управление устройствами', 'device_management:1', 'manage_devices'),
        ('📦 Минимум', 'tariff_select:1', 'tariff'),
        ('⚡ Автопродление через СБП', 'sbp_recurring_menu', 'autopay'),
        ('✅ Оплатить с баланса', 'simple_subscription_pay_with_balance', 'payment_pay'),
        ('💳 Привязанные карты', 'saved_cards_list', 'balance'),
        ('✅ Да, отвязать', 'confirm_unlink_1', 'confirm_switch'),
        ('📊 Проверить статус', 'check_yookassa_1', 'show_qr'),
        ('📅 30 дн.', 'noop', 'renewal_period'),
        ('📊 100 ГБ', 'noop', 'buy_traffic'),
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

    assert CUSTOM_EMOJI_IDS['confirm_purchase'] == '5397916757333654639'
    assert CUSTOM_EMOJI_IDS['channel_check'] == '5416081784641168838'
    assert CUSTOM_EMOJI_IDS['claim_discount'] == '5406683434124859552'
    assert CUSTOM_EMOJI_IDS['confirm_switch'] == '5206607081334906820'


def test_claim_discount_requested_icon_overrides_legacy_explicit_icon():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='🎁 Получить скидку',
                    callback_data='claim_discount_42',
                    icon_custom_emoji_id='5217822164362739968',
                )
            ]
        ]
    )

    button = apply_custom_emoji_icons(markup).inline_keyboard[0][0]

    assert button.text == 'Получить скидку'
    assert button.icon_custom_emoji_id == CUSTOM_EMOJI_IDS['claim_discount']


def test_quick_topup_amount_buttons_keep_only_explicit_icons():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='СБП (Lava)',
                    callback_data='topup_amount|lava_sbp|10000',
                    icon_custom_emoji_id=CUSTOM_EMOJI_IDS['balance_topup'],
                ),
                _button('300 ₽', callback_data='topup_amount|lava_sbp|30000'),
                _button('Банковская карта', callback_data='topup_amount|yookassa|30000'),
            ]
        ]
    )

    first, second, third = apply_custom_emoji_icons(markup).inline_keyboard[0]

    assert (first.text, first.icon_custom_emoji_id) == (
        'СБП (Lava)',
        CUSTOM_EMOJI_IDS['balance_topup'],
    )
    assert (second.text, second.icon_custom_emoji_id) == ('300 ₽', None)
    assert (third.text, third.icon_custom_emoji_id) == (
        'Банковская карта',
        CUSTOM_EMOJI_IDS['balance_topup'],
    )


def test_url_contact_and_all_back_cancel_buttons_are_decorated():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button('💬 Связаться с поддержкой', url='https://t.me/support')],
            [_button('⬅️ Назад', callback_data='anything')],
            [_button('🏠 В главное меню', callback_data='back_to_menu')],
            [_button('❌ Отмена', callback_data='anything_else')],
            [_button('🔗 Перейти к оплате', url='https://pay.example')],
            [_button('🆘 Обжаловать', url='https://t.me/support')],
        ]
    )

    contact, back, home, cancel, payment, appeal = [
        row[0] for row in apply_custom_emoji_icons(markup).inline_keyboard
    ]
    assert (contact.text, contact.icon_custom_emoji_id) == (
        'Связаться с поддержкой',
        CUSTOM_EMOJI_IDS['contact_support'],
    )
    assert (back.text, back.icon_custom_emoji_id) == ('Назад', CUSTOM_EMOJI_IDS['back'])
    assert (home.text, home.icon_custom_emoji_id) == ('В главное меню', CUSTOM_EMOJI_IDS['back'])
    assert (cancel.text, cancel.icon_custom_emoji_id) == ('Отмена', CUSTOM_EMOJI_IDS['cancel'])
    assert (payment.text, payment.icon_custom_emoji_id) == (
        'Перейти к оплате',
        CUSTOM_EMOJI_IDS['payment_pay'],
    )
    assert (appeal.text, appeal.icon_custom_emoji_id) == (
        'Обжаловать',
        CUSTOM_EMOJI_IDS['contact_support'],
    )


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


def test_legacy_privacy_policy_abbreviation_is_expanded():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[_button('🛡️ Политика конф.', callback_data='menu_privacy_policy')]]
    )

    button = apply_custom_emoji_icons(markup).inline_keyboard[0][0]

    assert button.text == 'Политика конфиденциальности'
    assert button.icon_custom_emoji_id == CUSTOM_EMOJI_IDS['privacy_policy']


def test_main_actions_use_supported_telegram_colors():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button('💎 Купить подписку', callback_data='menu_buy')],
            [_button('📱 Подписка', callback_data='menu_subscription')],
            [_button('💎 Купить подписку', callback_data='subscription_upgrade')],
            [_button('🧪 Тестовая подписка', callback_data='menu_trial')],
            [_button('🛠️ Техподдержка', callback_data='menu_support')],
            [_button('⬅️ К поддержке', callback_data='menu_support')],
        ]
    )

    buy, subscription, upgrade, trial, support, back = [
        row[0] for row in apply_custom_emoji_icons(markup).inline_keyboard
    ]
    assert buy.style == 'success'
    assert subscription.style == 'success'
    assert upgrade.style == 'success'
    assert trial.style == 'danger'
    assert support.style == 'primary'
    assert support.icon_custom_emoji_id == CUSTOM_EMOJI_IDS['support']
    assert back.style is None
