"""Apply the project's fixed custom emoji icons to outgoing inline keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.miniapp_buttons import strip_leading_emoji


CUSTOM_EMOJI_IDS: dict[str, str] = {
    'buy_main': '5472083403652210905',
    'trial': '5472279778146918060',
    'create_ticket': '5422360266618707867',
    'my_tickets': '5424818078833715060',
    'closed_tickets': '5210952531676504517',
    'privacy_policy': '5251203410396458957',
    'public_offer': '5334544901428229844',
    'contact_support': '5382355635553739365',
    'rules': '5471930335312747865',
    'back': '5350494198057412369',
    'cancel': '5402406965252989103',
    'activate': '5370896319210595146',
    'connect': '5443127283898405358',
    'buy_from_trial': '5372965424000409804',
    'confirm_purchase': '5397916757333654639',
    'my_subscription': '5373315485309870642',
    'extend_subscription': '5253478042256308885',
    'autopay': '5472193350520021357',
    'subscription_settings': '5341715473882955310',
    'tariff': '5471936197943106990',
    'buy_traffic': '5472287483318245416',
    'enable': '5416081784641168838',
    'disable': '5240241223632954241',
    'configure': '5341715473882955310',
    'renewal_period': '5253742260054409879',
    'manage_devices': '5251203410396458957',
    'revoke_subscription': '5395695537687123235',
    'cancel_ticket_creation': '5447183459602669338',
    'balance': '5451882707875276247',
    'promocode': '5431609822288033666',
    'referral_system': '5337080053119336309',
    'language': '5388632425314140043',
    'balance_history': '5282843764451195532',
    'balance_topup': '5449683594425410231',
    'create_invite': '5397916757333654639',
    'show_qr': '5231012545799666522',
    'referral_list': '5440539497383087970',
    'referral_analytics': '5231200819986047254',
    'support': '5472304422669262481',
}

PRIORITY_CALLBACK_TO_ICON: dict[str, str] = {
    'cancel_ticket_creation': 'cancel_ticket_creation',
}

CALLBACK_TO_ICON: dict[str, str] = {
    'menu_buy': 'buy_main',
    'menu_trial': 'trial',
    'return_to_saved_cart': 'back',
    'subscription_resume_checkout': 'back',
    'create_ticket': 'create_ticket',
    'my_tickets': 'my_tickets',
    'my_tickets_closed': 'closed_tickets',
    'menu_privacy_policy': 'privacy_policy',
    'menu_public_offer': 'public_offer',
    'menu_rules': 'rules',
    'trial_activate': 'activate',
    'subscription_connect': 'connect',
    'open_subscription_link': 'connect',
    'subscription_upgrade': 'buy_from_trial',
    'subscription_confirm': 'confirm_purchase',
    'simple_subscription_confirm_purchase': 'confirm_purchase',
    'tariff_confirm': 'confirm_purchase',
    'daily_tariff_confirm': 'confirm_purchase',
    'custom_confirm': 'confirm_purchase',
    'tariff_ext_confirm': 'confirm_purchase',
    'menu_subscription': 'my_subscription',
    'subscription_extend': 'extend_subscription',
    'subscription_autopay': 'autopay',
    'subscription_settings': 'subscription_settings',
    'instant_switch': 'tariff',
    'tariff_switch': 'tariff',
    'buy_traffic': 'buy_traffic',
    'autopay_enable': 'enable',
    'autopay_disable': 'disable',
    'autopay_set_days': 'configure',
    'autopay_set_period': 'renewal_period',
    'subscription_manage_devices': 'manage_devices',
    'subscription_revoke': 'revoke_subscription',
    'menu_balance': 'balance',
    'menu_promocode': 'promocode',
    'menu_referrals': 'referral_system',
    'menu_language': 'language',
    'balance_history': 'balance_history',
    'balance_topup': 'balance_topup',
    'referral_create_invite': 'create_invite',
    'referral_show_qr': 'show_qr',
    'referral_list': 'referral_list',
    'referral_analytics': 'referral_analytics',
    'menu_support': 'support',
}

CALLBACK_TO_STYLE: dict[str, str] = {
    'menu_buy': 'success',
    'menu_subscription': 'success',
    'subscription_upgrade': 'success',
    'simple_subscription_purchase': 'success',
    'menu_trial': 'danger',
    'menu_support': 'primary',
}

BACK_TEXT_MARKERS = (
    'назад',
    'back',
    'главное меню',
    'main menu',
    'головне меню',
    'на главную',
    'на головну',
    'к поддержке',
    'к тикетам',
    'home',
    'قبلی',
    'بازگشت',
    '返回',
)

CANCEL_TEXT_MARKERS = (
    'отмена',
    'cancel',
    'скасувати',
    'لغو',
    '取消',
)

CONTACT_SUPPORT_TEXTS = {
    'связаться с поддержкой',
    'contact support',
    "зв'язатися з підтримкою",
    'تماس با پشتیبانی',
    '联系支持',
}

CONNECT_TEXTS = {
    'подключиться',
    'connect',
    'підключитися',
    'اتصال',
    '连接',
}

LEGACY_BUTTON_TEXT_OVERRIDES: dict[tuple[str, str], str] = {
    ('menu_privacy_policy', 'политика конф.'): 'Политика конфиденциальности',
    ('menu_privacy_policy', 'політика конф.'): 'Політика конфіденційності',
}


def _resolve_icon_name(button: InlineKeyboardButton, plain_text: str) -> str | None:
    normalized_text = plain_text.strip().casefold()
    callback_name = (button.callback_data or '').split(':', 1)[0]

    priority_icon_name = PRIORITY_CALLBACK_TO_ICON.get(callback_name)
    if priority_icon_name:
        return priority_icon_name

    if any(marker in normalized_text for marker in BACK_TEXT_MARKERS):
        return 'back'
    if any(marker in normalized_text for marker in CANCEL_TEXT_MARKERS):
        return 'cancel'

    if button.icon_custom_emoji_id:
        return None

    icon_name = CALLBACK_TO_ICON.get(callback_name)
    if icon_name:
        return icon_name

    if normalized_text in CONTACT_SUPPORT_TEXTS:
        return 'contact_support'
    if normalized_text in CONNECT_TEXTS:
        return 'connect'
    return None


def apply_custom_emoji_icons(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Return a keyboard with fixed custom emoji icons and no duplicate Unicode icons."""
    changed = False
    rows: list[list[InlineKeyboardButton]] = []

    for row in markup.inline_keyboard:
        updated_row: list[InlineKeyboardButton] = []
        for button in row:
            plain_text = strip_leading_emoji(button.text)
            callback_name = (button.callback_data or '').split(':', 1)[0]
            plain_text = LEGACY_BUTTON_TEXT_OVERRIDES.get(
                (callback_name, plain_text.strip().casefold()),
                plain_text,
            )
            icon_name = _resolve_icon_name(button, plain_text)
            normalized_text = plain_text.strip().casefold()
            is_navigation = any(marker in normalized_text for marker in BACK_TEXT_MARKERS) or any(
                marker in normalized_text for marker in CANCEL_TEXT_MARKERS
            )
            style = button.style if is_navigation else CALLBACK_TO_STYLE.get(callback_name, button.style)

            if icon_name:
                emoji_id = CUSTOM_EMOJI_IDS[icon_name]
            else:
                emoji_id = button.icon_custom_emoji_id

            if (emoji_id and (button.text != plain_text or button.icon_custom_emoji_id != emoji_id)) or (
                button.style != style
            ):
                button = button.model_copy(
                    update={
                        'text': plain_text if emoji_id else button.text,
                        'icon_custom_emoji_id': emoji_id,
                        'style': style,
                    }
                )
                changed = True
            updated_row.append(button)
        rows.append(updated_row)

    return markup.model_copy(update={'inline_keyboard': rows}) if changed else markup


class CustomEmojiButtonsMiddleware:
    """Decorate inline keyboards immediately before Telegram API requests are sent."""

    async def __call__(self, make_request, bot, method):
        reply_markup = getattr(method, 'reply_markup', None)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            decorated_markup = apply_custom_emoji_icons(reply_markup)
            if decorated_markup is not reply_markup:
                method = method.model_copy(update={'reply_markup': decorated_markup})
        return await make_request(bot, method)
