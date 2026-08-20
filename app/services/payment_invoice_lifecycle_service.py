"""Lifecycle notifications for Telegram payment invoices.

The outgoing Telegram API middleware registers messages containing a payment
URL in the matching provider record.  A dedicated short-interval monitor then
warns the user shortly before expiry and replaces stale payment messages with
an explicit expiry notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.database import AsyncSessionLocal
from app.database.models import (
    AntilopayPayment,
    AuraPayPayment,
    CisPayPayment,
    DonutPayment,
    EtoplatezhiPayment,
    FreekassaPayment,
    HeleketPayment,
    JupiterPayment,
    KassaAiPayment,
    LavaPayment,
    OverpayPayment,
    Pal24Payment,
    PayPearPayment,
    PlategaPayment,
    RioPayPayment,
    RollyPayPayment,
    SeverPayPayment,
    User,
    WataPayment,
)
from app.localization.texts import get_texts


logger = structlog.get_logger(__name__)

LIFECYCLE_METADATA_KEY = 'telegram_invoice_lifecycle'
PAY_BUTTON_EMOJI_ID = '5271604874419647061'
WARNING_LINK_FRAGMENT = '#payment-expiry-reminder'


@dataclass(frozen=True, slots=True)
class PaymentModelSpec:
    provider: str
    model: type
    url_fields: tuple[str, ...] = ('payment_url',)


PAYMENT_MODEL_SPECS: tuple[PaymentModelSpec, ...] = (
    PaymentModelSpec('heleket', HeleketPayment),
    PaymentModelSpec('pal24', Pal24Payment, ('link_url', 'link_page_url')),
    PaymentModelSpec('wata', WataPayment, ('url',)),
    PaymentModelSpec('platega', PlategaPayment, ('redirect_url',)),
    PaymentModelSpec('freekassa', FreekassaPayment),
    PaymentModelSpec('kassa_ai', KassaAiPayment),
    PaymentModelSpec('riopay', RioPayPayment),
    PaymentModelSpec('severpay', SeverPayPayment),
    PaymentModelSpec('paypear', PayPearPayment),
    PaymentModelSpec('rollypay', RollyPayPayment),
    PaymentModelSpec('overpay', OverpayPayment),
    PaymentModelSpec('aurapay', AuraPayPayment),
    PaymentModelSpec('etoplatezhi', EtoplatezhiPayment),
    PaymentModelSpec('antilopay', AntilopayPayment),
    PaymentModelSpec('jupiter', JupiterPayment),
    PaymentModelSpec('donut', DonutPayment),
    PaymentModelSpec('lava', LavaPayment),
    PaymentModelSpec('cispay', CisPayPayment),
)

_PAID_STATUSES = {'paid', 'paid_over', 'success', 'succeeded', 'completed', 'confirmed'}
_PENDING_STATUSES = {'pending', 'new', 'process', 'processing', 'created', 'opened', 'active', 'check'}


def _extract_payment_urls(markup: InlineKeyboardMarkup | None) -> set[str]:
    if not markup:
        return set()
    return {
        button.url
        for row in markup.inline_keyboard
        for button in row
        if (
            button.url
            and button.url.startswith(('https://', 'http://'))
            and not button.url.endswith(WARNING_LINK_FRAGMENT)
        )
    }


def _is_paid(payment: Any) -> bool:
    paid_value = getattr(payment, 'is_paid', False)
    if isinstance(paid_value, bool) and paid_value:
        return True
    return str(getattr(payment, 'status', '') or '').strip().lower() in _PAID_STATUSES


def _is_pending(payment: Any) -> bool:
    if _is_paid(payment):
        return False

    pending_value = getattr(payment, 'is_pending', None)
    if isinstance(pending_value, bool):
        return pending_value

    return str(getattr(payment, 'status', '') or '').strip().lower() in _PENDING_STATUSES


async def _find_payment_by_urls(db: AsyncSession, urls: set[str]) -> tuple[PaymentModelSpec, Any] | None:
    candidates = []
    for spec in PAYMENT_MODEL_SPECS:
        url_columns = [getattr(spec.model, field) for field in spec.url_fields]
        candidates.append(
            select(spec.model)
            .with_only_columns(
                literal(spec.provider).label('provider'),
                spec.model.id.label('payment_id'),
                spec.model.created_at.label('created_at'),
            )
            .where(
                spec.model.user_id.isnot(None),
                spec.model.expires_at.isnot(None),
                or_(*(column.in_(urls) for column in url_columns)),
            )
        )

    matches = union_all(*candidates).subquery()
    result = await db.execute(
        select(matches.c.provider, matches.c.payment_id)
        .order_by(matches.c.created_at.desc())
        .limit(1)
    )
    match = result.first()
    if match is None:
        return None

    spec = next(spec for spec in PAYMENT_MODEL_SPECS if spec.provider == match.provider)
    payment = await db.get(spec.model, match.payment_id)
    return (spec, payment) if payment is not None else None


async def register_outgoing_payment_message(
    markup: InlineKeyboardMarkup | None,
    telegram_result: Any,
) -> None:
    """Persist the Telegram message that contains a provider payment URL."""
    urls = _extract_payment_urls(markup)
    if not urls or not isinstance(telegram_result, Message):
        return

    try:
        async with AsyncSessionLocal() as db:
            match = await _find_payment_by_urls(db, urls)
            if match is None:
                return

            spec, payment = match
            metadata = dict(payment.metadata_json or {})
            lifecycle = dict(metadata.get(LIFECYCLE_METADATA_KEY) or {})
            lifecycle.update(
                {
                    'chat_id': telegram_result.chat.id,
                    'invoice_message_id': telegram_result.message_id,
                    'provider': spec.provider,
                    'registered_at': datetime.now(UTC).isoformat(),
                }
            )
            metadata[LIFECYCLE_METADATA_KEY] = lifecycle
            payment.metadata_json = metadata
            await db.commit()
            logger.debug(
                'Payment invoice message registered',
                provider=spec.provider,
                payment_id=payment.id,
                message_id=telegram_result.message_id,
            )
    except Exception as error:
        # Registration must never turn a successfully sent invoice into a user-facing error.
        logger.warning('Failed to register payment invoice message', error=error)


def _localized_copy(language: str, key: str, texts) -> str:
    english = str(language or '').lower().startswith('en')
    fallbacks = {
        'warning': (
            '<tg-emoji emoji-id="5420323339723881652">⚠️</tg-emoji> '
            '<b>The invoice has not been paid yet</b>\n\n'
            'Less than 5 minutes remain before the payment link expires.'
            if english
            else '<tg-emoji emoji-id="5420323339723881652">⚠️</tg-emoji> '
            '<b>Счёт ещё не оплачен</b>\n\n'
            'До окончания срока оплаты осталось менее 5 минут.'
        ),
        'expired': (
            '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji> '
            '<b>The payment period has expired</b>\n\n'
            '<tg-emoji emoji-id="5451882707875276247">🕯</tg-emoji> Invoice amount: {amount}\n\n'
            'This invoice can no longer be paid. Create a new one to continue.'
            if english
            else '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji> '
            '<b>Срок оплаты истёк</b>\n\n'
            '<tg-emoji emoji-id="5451882707875276247">🕯</tg-emoji> Сумма счёта: {amount}\n\n'
            'Этот счёт больше нельзя оплатить. Создайте новый, чтобы продолжить.'
        ),
        'pay_button': 'Pay' if english else 'Оплатить',
        'main_button': 'Main menu' if english else 'Главное меню',
    }
    localization_keys = {
        'warning': 'PAYMENT_INVOICE_EXPIRING_WARNING',
        'expired': 'PAYMENT_INVOICE_EXPIRED',
        'pay_button': 'PAYMENT_INVOICE_PAY_BUTTON',
        'main_button': 'PAYMENT_INVOICE_MAIN_MENU_BUTTON',
    }
    return texts.t(localization_keys[key], fallbacks[key])


async def _delete_message_safely(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def delete_paid_invoice_messages(bot: Bot, payment: Any) -> None:
    """Delete the original invoice and its expiry warning after successful payment.

    Provider handlers may still update ``metadata_json`` after sending the
    success notification, so this immediate path deliberately does not mutate
    lifecycle metadata.  The periodic lifecycle worker persists ``closed_at``
    later; Telegram message deletion itself is safe to repeat.
    """
    metadata = dict(getattr(payment, 'metadata_json', None) or {})
    lifecycle = dict(metadata.get(LIFECYCLE_METADATA_KEY) or {})
    chat_id = lifecycle.get('chat_id')
    if not chat_id:
        return

    await _delete_message_safely(bot, int(chat_id), lifecycle.get('invoice_message_id'))
    await _delete_message_safely(bot, int(chat_id), lifecycle.get('warning_message_id'))


async def _store_lifecycle(db: AsyncSession, payment: Any, lifecycle: dict[str, Any]) -> None:
    metadata = dict(payment.metadata_json or {})
    metadata[LIFECYCLE_METADATA_KEY] = lifecycle
    payment.metadata_json = metadata
    await db.commit()


async def _send_warning(bot: Bot, db: AsyncSession, payment: Any, user: User, lifecycle: dict[str, Any]) -> None:
    chat_id = int(lifecycle['chat_id'])
    payment_url = next(
        (
            getattr(payment, field, None)
            for field in ('payment_url', 'redirect_url', 'link_url', 'link_page_url', 'url')
            if getattr(payment, field, None)
        ),
        None,
    )
    if not payment_url:
        return

    texts = get_texts(user.language)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_localized_copy(user.language, 'pay_button', texts),
                    # A URL fragment is not sent to the payment provider, but it
                    # prevents the outgoing-message registrar from mistaking the
                    # warning for the original invoice message.
                    url=f'{payment_url}{WARNING_LINK_FRAGMENT}',
                    icon_custom_emoji_id=PAY_BUTTON_EMOJI_ID,
                )
            ]
        ]
    )
    original_invoice_id = lifecycle.get('invoice_message_id')
    warning = await bot.send_message(
        chat_id=chat_id,
        text=_localized_copy(user.language, 'warning', texts),
        parse_mode='HTML',
        reply_markup=keyboard,
    )
    # Sending the warning itself also contains the payment URL and is therefore
    # seen by the registration middleware. Restore the original invoice id and
    # explicitly record the warning as the second message to clean up.
    lifecycle['invoice_message_id'] = original_invoice_id
    lifecycle['warning_message_id'] = warning.message_id
    lifecycle['warned_at'] = datetime.now(UTC).isoformat()
    await _store_lifecycle(db, payment, lifecycle)


async def _send_expired(bot: Bot, db: AsyncSession, payment: Any, user: User, lifecycle: dict[str, Any]) -> None:
    chat_id = int(lifecycle['chat_id'])
    await _delete_message_safely(bot, chat_id, lifecycle.get('invoice_message_id'))
    await _delete_message_safely(bot, chat_id, lifecycle.get('warning_message_id'))

    texts = get_texts(user.language)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_localized_copy(user.language, 'main_button', texts),
                    callback_data='back_to_menu',
                )
            ]
        ]
    )
    expired_message = await bot.send_message(
        chat_id=chat_id,
        text=_localized_copy(user.language, 'expired', texts).format(
            amount=texts.format_price(payment.amount_kopeks),
        ),
        parse_mode='HTML',
        reply_markup=keyboard,
    )
    lifecycle['expired_message_id'] = expired_message.message_id
    lifecycle['expired_notified_at'] = datetime.now(UTC).isoformat()
    await _store_lifecycle(db, payment, lifecycle)


async def _close_paid_invoice(bot: Bot, db: AsyncSession, payment: Any, lifecycle: dict[str, Any]) -> None:
    chat_id = int(lifecycle['chat_id'])
    await _delete_message_safely(bot, chat_id, lifecycle.get('invoice_message_id'))
    await _delete_message_safely(bot, chat_id, lifecycle.get('warning_message_id'))
    lifecycle['closed_at'] = datetime.now(UTC).isoformat()
    await _store_lifecycle(db, payment, lifecycle)


async def process_due_payment_invoices(bot: Bot) -> None:
    """Send five-minute warnings and replace expired invoice messages."""
    now = datetime.now(UTC)
    warning_minutes = max(1, int(getattr(settings, 'PAYMENT_INVOICE_WARNING_MINUTES', 5)))
    warning_cutoff = now + timedelta(minutes=warning_minutes)
    stale_cutoff = now - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        for spec in PAYMENT_MODEL_SPECS:
            result = await db.execute(
                select(spec.model)
                .where(
                    spec.model.user_id.isnot(None),
                    spec.model.expires_at.isnot(None),
                    spec.model.expires_at <= warning_cutoff,
                    spec.model.expires_at >= stale_cutoff,
                    spec.model.metadata_json.isnot(None),
                )
                .order_by(spec.model.expires_at.asc())
                .limit(200)
            )
            for payment in result.scalars().all():
                metadata = dict(payment.metadata_json or {})
                lifecycle = dict(metadata.get(LIFECYCLE_METADATA_KEY) or {})
                if not lifecycle or lifecycle.get('expired_notified_at') or lifecycle.get('closed_at'):
                    continue

                user = await db.get(User, payment.user_id)
                if user is None or not user.telegram_id or not lifecycle.get('chat_id'):
                    continue

                expires_at = payment.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)

                try:
                    if _is_paid(payment):
                        await _close_paid_invoice(bot, db, payment, lifecycle)
                    elif now >= expires_at:
                        await _send_expired(bot, db, payment, user, lifecycle)
                    elif _is_pending(payment) and not lifecycle.get('warned_at'):
                        await _send_warning(bot, db, payment, user, lifecycle)
                    elif not _is_pending(payment):
                        lifecycle['closed_at'] = now.isoformat()
                        await _store_lifecycle(db, payment, lifecycle)
                except (TelegramBadRequest, TelegramForbiddenError) as error:
                    logger.info(
                        'Payment invoice notification could not be delivered',
                        provider=spec.provider,
                        payment_id=payment.id,
                        error=error,
                    )
                except Exception as error:
                    logger.exception(
                        'Payment invoice lifecycle processing failed',
                        provider=spec.provider,
                        payment_id=payment.id,
                        error=error,
                    )
                    await db.rollback()
