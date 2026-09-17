"""Personal links issued by the old bot, redeemed atomically in the target bot."""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_migration_config import migration_bonus_kopeks, validate_migration_value
from app.config import settings
from app.database.crud.transaction import create_transaction
from app.database.crud.user import add_user_balance
from app.database.models import BotMigrationClaim, PaymentMethod, TransactionType, User, UserStatus


MIGRATION_START_PREFIX = 'move_'


def extract_migration_token(payload: str | None) -> str | None:
    if payload and re.fullmatch(r'move_[A-Za-z0-9_-]{43}', payload):
        return payload[len(MIGRATION_START_PREFIX) :]
    return None


def migration_target_username() -> str:
    url = validate_migration_value('BOT_MIGRATION_URL', settings.BOT_MIGRATION_URL)
    return urlsplit(url).path.lstrip('/').lower() if url else ''


@dataclass(frozen=True)
class MigrationLink:
    url: str
    amount_kopeks: int = 0


@dataclass(frozen=True)
class MigrationBonusResult:
    status: str
    amount_kopeks: int = 0


async def issue_migration_link(db: AsyncSession, telegram_id: int, source_bot_id: int) -> MigrationLink:
    """Unknown/blocked/deleted users get no bonus. Existing links retain their amount."""
    fallback = MigrationLink(settings.BOT_MIGRATION_URL)
    amount = migration_bonus_kopeks(settings.BOT_MIGRATION_BONUS_AMOUNT_RUBLES)
    if not settings.BOT_MIGRATION_BONUS_ENABLED or amount <= 0:
        return fallback
    target = migration_target_username()
    if not target:
        return fallback

    # All issue/redeem operations lock the owner first: consistent ordering.
    user = (
        await db.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not user or user.status != UserStatus.ACTIVE.value:
        return fallback
    claim = (
        await db.execute(select(BotMigrationClaim).where(BotMigrationClaim.user_id == user.id))
    ).scalar_one_or_none()
    if claim and claim.claimed_at:
        return fallback
    if claim is None:
        claim = BotMigrationClaim(
            user_id=user.id,
            token=secrets.token_urlsafe(32),
            source_bot_id=source_bot_id,
            target_bot_username=target,
            amount_kopeks=amount,
        )
        db.add(claim)
    elif claim.target_bot_username != target or claim.source_bot_id != source_bot_id:
        # A changed target invalidates previously issued links but cannot reset a claimed bonus.
        claim.token = secrets.token_urlsafe(32)
        claim.target_bot_username = target
        claim.source_bot_id = source_bot_id
        claim.amount_kopeks = amount
    await db.commit()
    return MigrationLink(f'https://t.me/{target}?start={MIGRATION_START_PREFIX}{claim.token}', claim.amount_kopeks)


async def claim_migration_bonus(
    db: AsyncSession,
    token: str,
    telegram_id: int,
    target_bot_id: int,
    target_bot_username: str,
) -> MigrationBonusResult:
    if not settings.BOT_MIGRATION_BONUS_ENABLED:
        return MigrationBonusResult('disabled')
    if migration_target_username() != (target_bot_username or '').lower():
        return MigrationBonusResult('invalid')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return MigrationBonusResult('invalid')

    try:
        user = (
            await db.execute(
                select(User)
                .where(User.telegram_id == telegram_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if not user or user.status != UserStatus.ACTIVE.value:
            return MigrationBonusResult('invalid')
        claim = (
            await db.execute(
                select(BotMigrationClaim)
                .where(BotMigrationClaim.user_id == user.id, BotMigrationClaim.token == token)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            not claim
            or claim.source_bot_id == target_bot_id
            or claim.target_bot_username != (target_bot_username or '').lower()
        ):
            return MigrationBonusResult('invalid')
        if claim.claimed_at:
            return MigrationBonusResult('already_claimed', claim.amount_kopeks)

        amount = claim.amount_kopeks
        success = await add_user_balance(db, user, amount, create_transaction=False, commit=False)
        if not success:
            raise RuntimeError('Migration balance update failed')
        await create_transaction(
            db,
            user.id,
            TransactionType.DEPOSIT,
            amount,
            'Бонус за переход в нового бота',
            payment_method=PaymentMethod.MANUAL,
            external_id=f'bot_migration_bonus:{user.id}',
            commit=False,
        )
        claim.claimed_at = datetime.now(UTC)
        # Balance, transaction and marker commit together; failures remain retryable.
        await db.commit()
        return MigrationBonusResult('credited', amount)
    except Exception:
        await db.rollback()
        raise
