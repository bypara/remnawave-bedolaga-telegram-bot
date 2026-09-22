"""PaymentService mixin for Anore (api.anore.cc)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import PaymentMethod, TransactionType
from app.services.anore_service import AnoreAPIError, anore_service
from app.utils.payment_logger import payment_logger as logger
from app.utils.user_utils import format_referrer_info


ANORE_STATUS_MAP: dict[str, tuple[str, bool]] = {
    'new': ('pending', False),
    'pending': ('pending', False),
    'paid': ('success', True),
    'expired': ('expired', False),
}
ANORE_PENDING_STATUSES = frozenset({'pending', 'new', 'creation_unknown'})
ANORE_FINAL_STATUSES = frozenset({'amount_mismatch'})
ANORE_ALLOWED_METHODS = frozenset({'sbp', 'yoomoney', 'crypto'})


def _amount_to_kopeks(value: Any) -> int | None:
    """Convert a RUB JSON number to integer kopecks without float drift."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value)) * Decimal(100)
        return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _configured_methods() -> str | None:
    raw = settings.ANORE_METHODS or ''
    methods = [item.strip().lower() for item in raw.split(',') if item.strip()]
    valid = [item for item in methods if item in ANORE_ALLOWED_METHODS]
    invalid = sorted(set(methods) - ANORE_ALLOWED_METHODS)
    if invalid:
        logger.warning('Anore: ignored unsupported payment methods', methods=invalid)
    return ','.join(dict.fromkeys(valid)) or None


class AnorePaymentMixin:
    """Create, verify, reconcile and finalize Anore payments."""

    async def create_anore_payment(
        self,
        db: AsyncSession,
        *,
        user_id: int | None,
        amount_kopeks: int,
        description: str = 'Пополнение баланса',
        email: str | None = None,
        language: str = 'ru',
        return_url: str | None = None,
        fail_url: str | None = None,
    ) -> dict[str, Any] | None:
        if not settings.is_anore_enabled():
            logger.error('Anore не настроен')
            return None
        if not settings.ANORE_MIN_AMOUNT_KOPEKS <= amount_kopeks <= settings.ANORE_MAX_AMOUNT_KOPEKS:
            logger.warning('Anore: сумма вне настроенных лимитов', amount_kopeks=amount_kopeks)
            return None

        payment_module = import_module('app.services.payment_service')
        user = await payment_module.get_user_by_id(db, user_id) if user_id is not None else None
        owner = getattr(user, 'telegram_id', None) or user_id or 'guest'
        order_id = f'an{owner}_{uuid.uuid4().hex[:10]}'[:64]
        metadata = {
            'user_id': user_id,
            'amount_kopeks': amount_kopeks,
            'description': description,
            'language': language,
            'type': 'balance_topup',
        }

        anore_crud = import_module('app.database.crud.anore')
        local_payment = await anore_crud.create_anore_payment(
            db=db,
            user_id=user_id,
            order_id=order_id,
            amount_kopeks=amount_kopeks,
            currency='RUB',
            description=description,
            is_test=anore_service.is_test_key,
            metadata_json=metadata,
        )

        try:
            api_result = await anore_service.create_payment(
                amount_kopeks=amount_kopeks,
                description=description,
                order_id=order_id,
                email=email,
                methods=_configured_methods(),
                success_url=return_url,
                fail_url=fail_url or return_url,
                callback_url=settings.ANORE_CALLBACK_URL,
            )
        except Exception as error:
            # The local row intentionally remains: if the HTTP response was
            # lost after Anore created the invoice, its webhook can still find
            # the order and credit it safely.
            # A deterministic 4xx means Anore rejected the request and did not
            # create an invoice. Network/5xx/incomplete-response outcomes stay
            # reconcilable because the provider may already have accepted it.
            is_deterministic_rejection = isinstance(error, AnoreAPIError) and 400 <= error.status_code < 500
            local_payment.status = 'error' if is_deterministic_rejection else 'creation_unknown'
            local_payment.callback_payload = {'creation_error': type(error).__name__}
            await db.commit()
            logger.exception('Anore: ошибка создания платежа', error=error, order_id=order_id)
            return None

        expires_in = api_result.get('expiresIn')
        try:
            expires_at = datetime.now(UTC) + timedelta(seconds=max(0, int(expires_in)))
        except (TypeError, ValueError):
            expires_at = datetime.now(UTC) + timedelta(hours=4)

        # A very fast webhook may have finalized the row while the create
        # request was still waiting for Anore. Reload it under a lock so the
        # provider response cannot overwrite ``success`` back to ``pending``.
        locked_payment = await anore_crud.get_anore_payment_by_id_for_update(db, local_payment.id)
        if locked_payment is not None:
            local_payment = locked_payment
        local_payment.anore_payment_id = str(api_result['id'])
        local_payment.payment_url = str(api_result['paymentUrl'])
        if not local_payment.is_paid:
            local_payment.status = ANORE_STATUS_MAP.get(
                str(api_result.get('status', '')).lower(),
                ('pending', False),
            )[0]
        local_payment.expires_at = expires_at
        local_payment.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(local_payment)

        return {
            'order_id': order_id,
            'payment_id': local_payment.anore_payment_id,
            'amount_kopeks': amount_kopeks,
            'amount_rubles': amount_kopeks / 100,
            'currency': 'RUB',
            'payment_url': local_payment.payment_url,
            'expires_at': expires_at.isoformat(),
            'local_payment_id': local_payment.id,
        }

    async def process_anore_callback(self, db: AsyncSession, payload: dict[str, Any]) -> bool:
        """Process an already signature-verified Anore webhook."""
        try:
            event = str(payload.get('event') or '').strip().lower()
            provider_id = str(payload.get('id') or '').strip()
            order_id = str(payload.get('orderId') or '').strip()
            delivery_id = str(payload.get('_delivery_id') or f'{event}:{provider_id}').strip()
            if event not in {'payment.succeeded', 'payment.expired'} or not provider_id or not order_id:
                logger.warning('Anore callback: malformed or unsupported event', event_name=event)
                return event.startswith('payout.')

            anore_crud = import_module('app.database.crud.anore')
            payment = await anore_crud.get_anore_payment_by_order_id(db, order_id)
            if not payment:
                logger.warning('Anore callback: payment not found', order_id=order_id, payment_id=provider_id)
                return True

            payment = await anore_crud.get_anore_payment_by_id_for_update(db, payment.id)
            if not payment:
                return False
            if anore_crud.is_anore_event_processed(payment, delivery_id):
                return True

            callback_payload = {key: value for key, value in payload.items() if not key.startswith('_')}

            if payment.anore_payment_id and payment.anore_payment_id != provider_id:
                anore_crud.remember_anore_event(payment, delivery_id)
                await anore_crud.update_anore_payment_status(
                    db=db,
                    payment=payment,
                    status='amount_mismatch',
                    is_paid=False,
                    callback_payload={'webhook': callback_payload, 'reason': 'provider_id_mismatch'},
                )
                return False

            # Persist the provider id before doing the server-side check. The
            # webhook endpoint ACKs in the background; if Anore's status API is
            # temporarily unavailable, the periodic reconciler can still retry
            # by this id instead of losing the only recovery handle.
            payment.anore_payment_id = provider_id
            payment.callback_payload = callback_payload
            payment.updated_at = datetime.now(UTC)
            await db.flush()

            if event == 'payment.expired':
                anore_crud.remember_anore_event(payment, delivery_id)
                await anore_crud.update_anore_payment_status(
                    db=db,
                    payment=payment,
                    status='expired',
                    anore_payment_id=provider_id,
                    callback_payload=callback_payload,
                )
                return True

            try:
                verified = await anore_service.get_payment(provider_id)
            except Exception as error:
                await db.commit()
                logger.error('Anore callback: server-side verification failed', error=error, payment_id=provider_id)
                return False

            if not self._anore_payment_matches(payment, verified, provider_id=provider_id):
                anore_crud.remember_anore_event(payment, delivery_id)
                await anore_crud.update_anore_payment_status(
                    db=db,
                    payment=payment,
                    status='amount_mismatch',
                    is_paid=False,
                    callback_payload={'webhook': callback_payload, 'verification': verified},
                )
                return False

            if payment.is_test or anore_service.is_test_key:
                payment.is_test = True
                anore_crud.remember_anore_event(payment, delivery_id)
                await anore_crud.update_anore_payment_status(
                    db=db,
                    payment=payment,
                    status='success',
                    anore_payment_id=provider_id,
                    callback_payload=callback_payload,
                )
                logger.info('Anore: test payment verified without crediting', order_id=order_id)
                return True

            if payment.is_paid:
                anore_crud.remember_anore_event(payment, delivery_id)
                await db.commit()
                return True

            payment.status = 'success'
            payment.is_paid = True
            payment.paid_at = datetime.now(UTC)
            payment.anore_payment_id = provider_id
            payment.payment_method = verified.get('method') or payment.payment_method
            payment.callback_payload = callback_payload
            payment.updated_at = datetime.now(UTC)
            anore_crud.remember_anore_event(payment, delivery_id)
            await db.flush()
            return await self._finalize_anore_payment(db, payment, trigger='webhook')
        except Exception as error:
            logger.exception('Anore callback: processing error', error=error)
            return False

    @staticmethod
    def _anore_payment_matches(payment: Any, data: dict[str, Any], *, provider_id: str) -> bool:
        received = _amount_to_kopeks(data.get('rubAmount', data.get('amount')))
        # The create response contains orderId, while the status endpoint's
        # documented response may omit it. If it is present it must match;
        # otherwise provider id + paid flag + amount still bind the payment.
        returned_order_id = data.get('orderId')
        order_matches = returned_order_id is None or str(returned_order_id) == payment.order_id
        return bool(
            str(data.get('id') or '') == provider_id
            and order_matches
            and str(data.get('status') or '').lower() == 'paid'
            and data.get('paid') is True
            and str(data.get('currency') or 'rub').lower() == 'rub'
            and received == payment.amount_kopeks
        )

    async def _finalize_anore_payment(self, db: AsyncSession, payment: Any, *, trigger: str) -> bool:
        payment_module = import_module('app.services.payment_service')
        anore_crud = import_module('app.database.crud.anore')

        if payment.is_test:
            return True
        if payment.transaction_id:
            return True

        metadata = dict(payment.metadata_json or {})
        from app.services.payment.common import try_fulfill_guest_purchase

        guest_result = await try_fulfill_guest_purchase(
            db,
            metadata=metadata,
            payment_amount_kopeks=payment.amount_kopeks,
            provider_payment_id=payment.anore_payment_id or payment.order_id,
            provider_name='anore',
        )
        if guest_result is not None:
            return True

        user = await payment_module.get_user_by_id(db, payment.user_id)
        if not user:
            logger.error('Anore: user not found', user_id=payment.user_id, order_id=payment.order_id)
            return False

        await db.refresh(user, attribute_names=['promo_group', 'user_promo_groups'])
        for membership in getattr(user, 'user_promo_groups', []):
            await db.refresh(membership, attribute_names=['promo_group'])

        promo_group = user.get_primary_promo_group()
        subscription = getattr(user, 'subscription', None)
        referrer_info = format_referrer_info(user)
        existing = await payment_module.get_transaction_by_external_id(db, payment.order_id, PaymentMethod.ANORE)
        transaction = existing
        created_transaction = False
        if transaction is None:
            transaction = await payment_module.create_transaction(
                db,
                user_id=payment.user_id,
                type=TransactionType.DEPOSIT,
                amount_kopeks=payment.amount_kopeks,
                description=f'Пополнение через {settings.get_anore_display_name()}',
                payment_method=PaymentMethod.ANORE,
                external_id=payment.order_id,
                is_completed=True,
                created_at=payment.created_at,
                commit=False,
            )
            created_transaction = True

        await anore_crud.link_anore_payment_to_transaction(db, payment=payment, transaction_id=transaction.id)
        if not created_transaction and metadata.get('balance_credited'):
            return True

        from app.database.crud.user import lock_user_for_update

        user = await lock_user_for_update(db, user)
        old_balance = user.balance_kopeks
        was_first_topup = not user.has_made_first_topup
        user.balance_kopeks += payment.amount_kopeks
        user.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(user)

        from app.database.crud.transaction import emit_transaction_side_effects

        await emit_transaction_side_effects(
            db,
            transaction,
            amount_kopeks=payment.amount_kopeks,
            user_id=payment.user_id,
            type=TransactionType.DEPOSIT,
            payment_method=PaymentMethod.ANORE,
            external_id=payment.order_id,
        )

        try:
            from app.services.referral_service import process_referral_topup

            await process_referral_topup(db, user.id, payment.amount_kopeks, getattr(self, 'bot', None))
        except Exception as error:
            logger.error('Anore: referral processing failed', error=error)

        if was_first_topup and not user.has_made_first_topup and not user.referred_by_id:
            user.has_made_first_topup = True
            await db.commit()
            await db.refresh(user)

        if getattr(self, 'bot', None):
            try:
                from app.services.admin_notification_service import AdminNotificationService

                await AdminNotificationService(self.bot).send_balance_topup_notification(
                    user,
                    transaction,
                    old_balance,
                    topup_status='🆕 Первое пополнение' if was_first_topup else '🔄 Пополнение',
                    referrer_info=referrer_info,
                    subscription=subscription,
                    promo_group=promo_group,
                    db=db,
                )
            except Exception as error:
                logger.error('Anore: admin notification failed', error=error)

        if getattr(self, 'bot', None) and user.telegram_id and settings.is_notifications_enabled():
            try:
                await self._send_payment_success_notification(
                    user.telegram_id,
                    payment.amount_kopeks,
                    user,
                    db=db,
                    payment=payment,
                    payment_method_title=settings.get_anore_display_name(),
                )
            except Exception as error:
                logger.error('Anore: user notification failed', error=error)

        from app.services.payment.common import send_cart_notification_after_topup

        try:
            await send_cart_notification_after_topup(user, payment.amount_kopeks, db, getattr(self, 'bot', None))
        except Exception as error:
            logger.error('Anore: cart processing failed after successful credit', error=error)

        metadata['balance_change'] = {
            'old_balance': old_balance,
            'new_balance': user.balance_kopeks,
            'credited_at': datetime.now(UTC).isoformat(),
        }
        metadata['balance_credited'] = True
        payment.metadata_json = metadata
        await db.commit()
        logger.info('Anore payment finalized', order_id=payment.order_id, trigger=trigger)
        return True

    async def check_anore_payment_status(self, db: AsyncSession, order_id: str) -> dict[str, Any] | None:
        anore_crud = import_module('app.database.crud.anore')
        payment = await anore_crud.get_anore_payment_by_order_id(db, order_id)
        if not payment:
            return None
        if payment.is_paid:
            return {'payment': payment, 'status': payment.status, 'is_paid': True}
        if payment.status in ANORE_FINAL_STATUSES or not payment.anore_payment_id:
            return {'payment': payment, 'status': payment.status, 'is_paid': False}

        try:
            data = await anore_service.get_payment(payment.anore_payment_id)
        except Exception as error:
            logger.error('Anore status check failed', error=error, order_id=order_id)
            return {'payment': payment, 'status': payment.status, 'is_paid': False}

        provider_status = str(data.get('status') or '').lower()
        internal_status, is_paid = ANORE_STATUS_MAP.get(provider_status, ('pending', False))
        if not is_paid:
            if payment.status != internal_status:
                payment = await anore_crud.update_anore_payment_status(db=db, payment=payment, status=internal_status)
            return {'payment': payment, 'status': payment.status, 'is_paid': False}

        if not self._anore_payment_matches(payment, data, provider_id=payment.anore_payment_id):
            payment = await anore_crud.update_anore_payment_status(
                db=db,
                payment=payment,
                status='amount_mismatch',
                is_paid=False,
                callback_payload={'check_source': 'api', 'verification': data},
            )
            return {'payment': payment, 'status': payment.status, 'is_paid': False}

        if payment.is_test or anore_service.is_test_key:
            payment.is_test = True
            payment = await anore_crud.update_anore_payment_status(db=db, payment=payment, status='success')
            return {'payment': payment, 'status': payment.status, 'is_paid': False}

        payment = await anore_crud.get_anore_payment_by_id_for_update(db, payment.id)
        if payment.is_paid:
            return {'payment': payment, 'status': payment.status, 'is_paid': True}
        payment.status = 'success'
        payment.is_paid = True
        payment.paid_at = datetime.now(UTC)
        payment.payment_method = data.get('method') or payment.payment_method
        payment.callback_payload = {'check_source': 'api', 'verification': data}
        payment.updated_at = datetime.now(UTC)
        await db.flush()
        await self._finalize_anore_payment(db, payment, trigger='api_check')
        return {'payment': payment, 'status': payment.status, 'is_paid': payment.is_paid}
