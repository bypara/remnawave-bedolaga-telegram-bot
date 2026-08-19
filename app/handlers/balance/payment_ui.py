"""Shared user-facing UI for balance top-up providers.

Payment handlers should keep provider-specific API calls and status processing, while
using this module for the screens that are identical from a user's point of view.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.localization.texts import get_texts


TOPUP_EMOJI_ID = '5449683594425410231'
AMOUNT_EMOJI_ID = '5451882707875276247'
INSTRUCTIONS_EMOJI_ID = '5231012545799666522'
ERROR_EMOJI_ID = '5210952531676504517'
WARNING_EMOJI_ID = '5420323339723881652'
PAY_BUTTON_EMOJI_ID = '5271604874419647061'
APPEAL_BUTTON_EMOJI_ID = '5253742260054409879'


def _is_english(language: str | None) -> bool:
    return str(language or '').lower().startswith('en')


def format_rubles(amount_kopeks: int, *, decimals: bool = False) -> str:
    """Format kopeks consistently for all payment screens."""
    amount = amount_kopeks / 100
    if decimals and amount_kopeks % 100:
        value = f'{amount:,.2f}'
    else:
        value = f'{amount:,.0f}'
    return value.replace(',', ' ')


def build_topup_prompt(
    language: str,
    method_name: str,
    min_amount_kopeks: int,
    max_amount_kopeks: int,
    *,
    note: str | None = None,
) -> str:
    method = html.escape(method_name)
    minimum = format_rubles(min_amount_kopeks, decimals=True)
    maximum = format_rubles(max_amount_kopeks, decimals=True)
    if _is_english(language):
        text = (
            f'<tg-emoji emoji-id="{TOPUP_EMOJI_ID}">🔼</tg-emoji> '
            f'<b>Payment via {method}</b>\n\n'
            f'Enter a top-up amount from <b>{minimum} ₽</b> to <b>{maximum} ₽</b>.'
        )
    else:
        text = (
            f'<tg-emoji emoji-id="{TOPUP_EMOJI_ID}">🔼</tg-emoji> '
            f'<b>Оплата через {method}</b>\n\n'
            f'Введите сумму для пополнения от <b>{minimum} ₽</b> до <b>{maximum} ₽</b>.'
        )
    if note:
        text += f'\n\n{note}'
    return text


def build_payment_created_text(
    language: str,
    method_name: str,
    amount_kopeks: int,
    *,
    details: Sequence[str] = (),
    instruction: bool = True,
) -> str:
    """Build the standard invoice screen; provider-only details can be appended."""
    method = html.escape(method_name)
    amount = format_rubles(amount_kopeks, decimals=True)
    if _is_english(language):
        parts = [
            f'<tg-emoji emoji-id="{TOPUP_EMOJI_ID}">🔼</tg-emoji> <b>Payment via {method}</b>',
            f'<tg-emoji emoji-id="{AMOUNT_EMOJI_ID}">🕯</tg-emoji> Amount: <b>{amount} ₽</b>',
        ]
        if details:
            parts.append('\n'.join(details))
        if instruction:
            parts.append(
                f'<tg-emoji emoji-id="{INSTRUCTIONS_EMOJI_ID}">🔍</tg-emoji> <b>Instructions:</b>\n'
                '1. Tap “Pay”\n'
                '2. Follow the payment system instructions\n'
                '3. Confirm the transfer\n'
                '4. The funds will be credited automatically'
            )
    else:
        parts = [
            f'<tg-emoji emoji-id="{TOPUP_EMOJI_ID}">🔼</tg-emoji> <b>Оплата через {method}</b>',
            f'<tg-emoji emoji-id="{AMOUNT_EMOJI_ID}">🕯</tg-emoji> Сумма: <b>{amount} ₽</b>',
        ]
        if details:
            parts.append('\n'.join(details))
        if instruction:
            parts.append(
                f'<tg-emoji emoji-id="{INSTRUCTIONS_EMOJI_ID}">🔍</tg-emoji> <b>Инструкция:</b>\n'
                '1. Нажмите кнопку «Оплатить»\n'
                '2. Следуйте подсказкам платёжной системы\n'
                '3. Подтвердите перевод\n'
                '4. Средства зачислятся автоматически'
            )
    return '\n\n'.join(parts)


def build_payment_processing_text(language: str, method_name: str, amount_kopeks: int) -> str:
    method = html.escape(method_name)
    amount = format_rubles(amount_kopeks, decimals=True)
    if _is_english(language):
        status = 'The payment is being processed. The payment link will be sent separately.'
        heading = f'Payment via {method}'
        amount_label = 'Amount'
    else:
        status = 'Платёж в обработке. Ссылка на оплату будет отправлена отдельно.'
        heading = f'Оплата через {method}'
        amount_label = 'Сумма'
    return (
        f'<tg-emoji emoji-id="{TOPUP_EMOJI_ID}">🔼</tg-emoji> <b>{heading}</b>\n\n'
        f'<tg-emoji emoji-id="{AMOUNT_EMOJI_ID}">🕯</tg-emoji> {amount_label}: <b>{amount} ₽</b>\n\n'
        f'{status}'
    )


def build_payment_keyboard(
    language: str,
    payment_url: str | None,
    amount_kopeks: int,
    *,
    back_callback: str = 'menu_balance',
) -> InlineKeyboardMarkup:
    texts = get_texts(language)
    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        pay = 'Pay' if _is_english(language) else 'Оплатить'
        rows.append(
            [
                InlineKeyboardButton(
                    text=f'{pay} {format_rubles(amount_kopeks, decimals=True)} ₽',
                    url=payment_url,
                    icon_custom_emoji_id=PAY_BUTTON_EMOJI_ID,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=texts.BACK, callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_payment_create_error(language: str) -> str:
    if _is_english(language):
        message = 'Failed to create the payment. Please try again later.'
    else:
        message = 'Не удалось создать платёж. Попробуйте позже.'
    return f'<tg-emoji emoji-id="{ERROR_EMOJI_ID}">❌</tg-emoji> {message}'


def build_amount_error(language: str, amount_kopeks: int, *, minimum: bool) -> str:
    amount = format_rubles(amount_kopeks, decimals=True)
    if _is_english(language):
        message = f'The {"minimum" if minimum else "maximum"} top-up amount is <b>{amount} ₽</b>.'
    else:
        word = 'Минимальная' if minimum else 'Максимальная'
        message = f'{word} сумма пополнения: <b>{amount} ₽</b>.'
    return f'<tg-emoji emoji-id="{WARNING_EMOJI_ID}">⚠️</tg-emoji> {message}'


def build_topup_restriction_text(language: str, reason: str | None) -> str:
    safe_reason = html.escape(reason or ('Restricted by administrator' if _is_english(language) else 'Действие ограничено администратором'))
    title = 'Top-ups are restricted' if _is_english(language) else 'Пополнение ограничено'
    return f'<tg-emoji emoji-id="{ERROR_EMOJI_ID}">❌</tg-emoji> <b>{title}</b>\n\n{safe_reason}'


def build_topup_restriction_keyboard(language: str) -> InlineKeyboardMarkup:
    texts = get_texts(language)
    rows: list[list[InlineKeyboardButton]] = []
    support_url = settings.get_support_contact_url()
    if support_url:
        appeal = 'Appeal' if _is_english(language) else 'Обжаловать'
        rows.append(
            [
                InlineKeyboardButton(
                    text=appeal,
                    url=support_url,
                    icon_custom_emoji_id=APPEAL_BUTTON_EMOJI_ID,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=texts.BACK, callback_data='menu_balance')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
