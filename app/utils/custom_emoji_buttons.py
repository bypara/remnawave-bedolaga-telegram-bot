"""Apply the project's fixed custom emoji icons to outgoing inline keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.miniapp_buttons import strip_leading_emoji


CUSTOM_EMOJI_IDS: dict[str, str] = {
    'buy_main': '5472083403652210905',
    'trial': '5472279778146918060',
    'create_ticket': '5422360266618707867',
    'my_tickets': '5388658581664993142',
    'contact_support': '5382355635553739365',
    'rules': '5471930335312747865',
    'back': '5350494198057412369',
    'cancel': '5402406965252989103',
    'activate': '5370896319210595146',
    'connect': '5443127283898405358',
    'buy_from_trial': '5372965424000409804',
    'confirm_purchase': '5206401524200145033',
    'my_subscription': '5373315485309870642',
    'extend_subscription': '5253478042256308885',
    'autopay': '5472193350520021357',
    'subscription_settings': '5350396951407895212',
    'tariff': '5471936197943106990',
    'buy_traffic': '5472287483318245416',
}

CALLBACK_TO_ICON: dict[str, str] = {
    'menu_buy': 'buy_main',
    'menu_trial': 'trial',
    'return_to_saved_cart': 'back',
    'subscription_resume_checkout': 'back',
    'create_ticket': 'create_ticket',
    'my_tickets': 'my_tickets',
    'menu_rules': 'rules',
    'trial_activate': 'activate',
    'subscription_connect': 'connect',
    'open_subscription_link': 'connect',
    'subscription_upgrade': 'buy_from_trial',
    'subscription_confirm': 'confirm_purchase',
    'simple_subscription_confirm_purchase': 'confirm_purchase',
    'menu_subscription': 'my_subscription',
    'subscription_extend': 'extend_subscription',
    'subscription_autopay': 'autopay',
    'subscription_settings': 'subscription_settings',
    'instant_switch': 'tariff',
    'tariff_switch': 'tariff',
    'buy_traffic': 'buy_traffic',
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


def _resolve_icon_name(button: InlineKeyboardButton, plain_text: str) -> str | None:
    normalized_text = plain_text.strip().casefold()

    if any(marker in normalized_text for marker in BACK_TEXT_MARKERS):
        return 'back'
    if any(marker in normalized_text for marker in CANCEL_TEXT_MARKERS):
        return 'cancel'

    if button.icon_custom_emoji_id:
        return None

    callback_name = (button.callback_data or '').split(':', 1)[0]
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
            icon_name = _resolve_icon_name(button, plain_text)

            if icon_name:
                emoji_id = CUSTOM_EMOJI_IDS[icon_name]
            else:
                emoji_id = button.icon_custom_emoji_id

            if emoji_id and (button.text != plain_text or button.icon_custom_emoji_id != emoji_id):
                button = button.model_copy(
                    update={
                        'text': plain_text,
                        'icon_custom_emoji_id': emoji_id,
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
