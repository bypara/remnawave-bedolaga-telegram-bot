"""CRUD operations for payments accepted through api.anore.cc."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AnorePayment


logger = structlog.get_logger(__name__)


async def create_anore_payment(
    db: AsyncSession,
    *,
    user_id: int | None,
    order_id: str,
    amount_kopeks: int,
    currency: str = 'RUB',
    description: str | None = None,
    payment_url: str | None = None,
    payment_method: str | None = None,
    anore_payment_id: str | None = None,
    is_test: bool = False,
    expires_at: datetime | None = None,
    metadata_json: dict | None = None,
) -> AnorePayment:
    """Создаёт запись о платеже Anore."""
    payment = AnorePayment(
        user_id=user_id,
        order_id=order_id,
        amount_kopeks=amount_kopeks,
        currency=currency,
        description=description,
        payment_url=payment_url,
        payment_method=payment_method,
        anore_payment_id=anore_payment_id,
        is_test=is_test,
        expires_at=expires_at,
        metadata_json=metadata_json,
        processed_events=[],
        status='pending',
        is_paid=False,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    logger.info('Создан платеж Anore', order_id=order_id, user_id=user_id)
    return payment


async def get_anore_payment_by_order_id(db: AsyncSession, order_id: str) -> AnorePayment | None:
    """Получает платеж по order_id (наш)."""
    result = await db.execute(select(AnorePayment).where(AnorePayment.order_id == order_id))
    return result.scalar_one_or_none()


async def get_anore_payment_by_invoice_id(db: AsyncSession, anore_payment_id: str) -> AnorePayment | None:
    """Получает платёж по идентификатору, выданному Anore."""
    result = await db.execute(select(AnorePayment).where(AnorePayment.anore_payment_id == anore_payment_id))
    return result.scalar_one_or_none()


async def get_anore_payment_by_id(db: AsyncSession, payment_id: int) -> AnorePayment | None:
    """Получает платеж по локальному ID."""
    result = await db.execute(select(AnorePayment).where(AnorePayment.id == payment_id))
    return result.scalar_one_or_none()


async def get_anore_payment_by_id_for_update(db: AsyncSession, payment_id: int) -> AnorePayment | None:
    """Получает платёж с блокировкой FOR UPDATE."""
    result = await db.execute(
        select(AnorePayment)
        .where(AnorePayment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def update_anore_payment_status(
    db: AsyncSession,
    payment: AnorePayment,
    *,
    status: str,
    is_paid: bool | None = None,
    anore_payment_id: str | None = None,
    payment_method: str | None = None,
    callback_payload: dict | None = None,
    transaction_id: int | None = None,
) -> AnorePayment:
    """Обновляет статус платежа."""
    payment.status = status
    payment.updated_at = datetime.now(UTC)

    if is_paid is not None:
        payment.is_paid = is_paid
        if is_paid:
            payment.paid_at = datetime.now(UTC)
    if anore_payment_id is not None:
        payment.anore_payment_id = anore_payment_id
    if payment_method is not None:
        payment.payment_method = payment_method
    if callback_payload is not None:
        payment.callback_payload = callback_payload
    if transaction_id is not None:
        payment.transaction_id = transaction_id

    await db.commit()
    await db.refresh(payment)
    logger.info(
        'Обновлён статус платежа Anore',
        order_id=payment.order_id,
        status=status,
        is_paid=payment.is_paid,
    )
    return payment


def is_anore_event_processed(payment: AnorePayment, event_key: str) -> bool:
    """Whether a webhook delivery ID has already been processed."""
    return event_key in (payment.processed_events or [])


def remember_anore_event(payment: AnorePayment, event_key: str) -> None:
    """Mark a webhook delivery ID as processed.

    Список пересобирается, а не мутируется на месте: SQLAlchemy отслеживает
    изменения JSON-колонки по присваиванию, иначе апдейт не попал бы в UPDATE.
    """
    processed = list(payment.processed_events or [])
    if event_key not in processed:
        processed.append(event_key)
    payment.processed_events = processed


async def get_pending_anore_payments(db: AsyncSession, user_id: int) -> list[AnorePayment]:
    """Возвращает незавершённые платежи пользователя."""
    result = await db.execute(
        select(AnorePayment).where(
            AnorePayment.user_id == user_id,
            AnorePayment.status == 'pending',
            AnorePayment.is_paid == False,
        )
    )
    return list(result.scalars().all())


async def link_anore_payment_to_transaction(
    db: AsyncSession,
    *,
    payment: AnorePayment,
    transaction_id: int,
) -> AnorePayment:
    """Связывает платёж с транзакцией."""
    payment.transaction_id = transaction_id
    payment.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(payment)
    return payment

