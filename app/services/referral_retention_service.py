"""Delayed rewards for referrals that remain reachable and subscribed."""

import html
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import (
    ReferralEarning,
    ReferralRetentionReward,
    ReferralRetentionRewardStatus,
    Transaction,
    TransactionType,
    User,
    UserStatus,
)
from app.services.channel_subscription_service import channel_subscription_service


logger = structlog.get_logger(__name__)


async def schedule_referral_retention_reward(
    db: AsyncSession,
    *,
    referral_id: int,
    referrer_id: int,
) -> ReferralRetentionReward | None:
    """Create one immutable delayed reward for a newly registered referral."""
    amount = max(int(settings.REFERRAL_RETENTION_REWARD_KOPEKS or 0), 0)
    if not settings.REFERRAL_RETENTION_REWARD_ENABLED or amount <= 0:
        return None

    existing = await db.scalar(
        select(ReferralRetentionReward).where(ReferralRetentionReward.referral_id == referral_id)
    )
    if existing:
        return existing

    reward = ReferralRetentionReward(
        referrer_id=referrer_id,
        referral_id=referral_id,
        amount_kopeks=amount,
        eligible_at=datetime.now(UTC) + timedelta(days=max(int(settings.REFERRAL_RETENTION_DAYS or 0), 0)),
    )
    db.add(reward)
    try:
        await db.commit()
        await db.refresh(reward)
        logger.info(
            'Referral retention reward scheduled',
            reward_id=reward.id,
            referrer_id=referrer_id,
            referral_id=referral_id,
            amount_kopeks=amount,
            eligible_at=reward.eligible_at,
        )
        return reward
    except IntegrityError:
        await db.rollback()
        return await db.scalar(
            select(ReferralRetentionReward).where(ReferralRetentionReward.referral_id == referral_id)
        )


def _confirmed_unreachable(error: Exception) -> bool:
    if isinstance(error, TelegramForbiddenError):
        return True
    if not isinstance(error, TelegramBadRequest):
        return False
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            'bot was blocked by the user',
            'chat not found',
            'user is deactivated',
            'user not found',
            "bot can't initiate conversation",
            "can't initiate conversation",
            'peer_id_invalid',
        )
    )


async def _check_bot_reachability(bot: Bot, telegram_id: int) -> bool | None:
    """Use a harmless chat action because Bot API has no read-only block check."""
    try:
        await bot.send_chat_action(telegram_id, ChatAction.TYPING)
        return True
    except TelegramAPIError as error:
        if _confirmed_unreachable(error):
            return False
        logger.warning('Referral reachability check uncertain', telegram_id=telegram_id, error=error)
        return None


async def _reject(db: AsyncSession, reward: ReferralRetentionReward, reason: str, now: datetime) -> None:
    reward.status = ReferralRetentionRewardStatus.REJECTED.value
    reward.rejection_reason = reason
    reward.last_checked_at = now
    reward.completed_at = now
    reward.updated_at = now
    await db.commit()
    logger.info('Referral retention reward rejected', reward_id=reward.id, reason=reason)


async def _notify_reward(bot: Bot, referrer: User, referral: User, amount_kopeks: int) -> None:
    if not referrer.telegram_id:
        return
    amount = settings.format_price(amount_kopeks)
    referral_name = html.escape(referral.full_name or referral.username or f'#{referral.id}')
    if str(referrer.language or '').lower().startswith('en'):
        text = (
            '<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> <b>Referral reward received!</b>'
            f'\n\nYour referral <b>{referral_name}</b> completed the verification period.'
            f'\nCredited to your balance: <b>{amount}</b>'
        )
    else:
        text = (
            '<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> <b>Реферальная награда получена!</b>'
            f'\n\nВаш реферал <b>{referral_name}</b> прошёл проверочный период.'
            f'\nНа ваш баланс начислено: <b>{amount}</b>'
        )
    try:
        await bot.send_message(referrer.telegram_id, text, parse_mode='HTML')
    except TelegramAPIError as error:
        logger.warning('Failed to notify referrer about retention reward', referrer_id=referrer.id, error=error)


async def process_due_referral_retention_rewards(db: AsyncSession, bot: Bot) -> dict[str, int]:
    """Verify and settle due rewards once, safely across multiple workers."""
    stats = {'checked': 0, 'rewarded': 0, 'rejected': 0, 'deferred': 0}
    if not settings.REFERRAL_RETENTION_REWARD_ENABLED:
        return stats

    now = datetime.now(UTC)
    limit = max(1, min(int(settings.REFERRAL_RETENTION_BATCH_SIZE or 100), 1000))
    result = await db.execute(
        select(ReferralRetentionReward.id)
        .where(
            ReferralRetentionReward.status == ReferralRetentionRewardStatus.PENDING.value,
            ReferralRetentionReward.eligible_at <= now,
        )
        .order_by(ReferralRetentionReward.eligible_at, ReferralRetentionReward.id)
        .limit(limit)
    )
    reward_ids = list(result.scalars().all())
    channel_subscription_service.bot = bot

    for reward_id in reward_ids:
        reward = await db.scalar(
            select(ReferralRetentionReward)
            .options(
                selectinload(ReferralRetentionReward.referrer),
                selectinload(ReferralRetentionReward.referral),
            )
            .where(
                ReferralRetentionReward.id == reward_id,
                ReferralRetentionReward.status == ReferralRetentionRewardStatus.PENDING.value,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if not reward:
            continue
        stats['checked'] += 1
        referral = reward.referral
        referrer = reward.referrer
        if (
            not referral
            or not referrer
            or referral.referred_by_id != referrer.id
            or referral.status != UserStatus.ACTIVE.value
            or not referral.telegram_id
        ):
            await _reject(db, reward, 'invalid_or_inactive_referral', now)
            stats['rejected'] += 1
            continue

        channel_status = await channel_subscription_service.check_required_channels_strict(referral.telegram_id)
        if channel_status is None:
            reward.last_checked_at = now
            reward.updated_at = now
            await db.commit()
            stats['deferred'] += 1
            continue
        if channel_status is False:
            await _reject(db, reward, 'required_channel_not_subscribed', now)
            stats['rejected'] += 1
            continue

        reachable = await _check_bot_reachability(bot, referral.telegram_id)
        if reachable is None:
            reward.last_checked_at = now
            reward.updated_at = now
            await db.commit()
            stats['deferred'] += 1
            continue
        if reachable is False:
            await _reject(db, reward, 'bot_blocked_or_account_unavailable', now)
            stats['rejected'] += 1
            continue

        locked_referrer = await db.scalar(select(User).where(User.id == referrer.id).with_for_update())
        if not locked_referrer or locked_referrer.status != UserStatus.ACTIVE.value:
            await _reject(db, reward, 'invalid_or_inactive_referrer', now)
            stats['rejected'] += 1
            continue

        locked_referrer.balance_kopeks += reward.amount_kopeks
        locked_referrer.updated_at = now
        db.add(
            Transaction(
                user_id=locked_referrer.id,
                type=TransactionType.REFERRAL_REWARD.value,
                amount_kopeks=reward.amount_kopeks,
                description=f'Награда за активного реферала {referral.full_name}',
                is_completed=True,
                completed_at=now,
            )
        )
        db.add(
            ReferralEarning(
                user_id=locked_referrer.id,
                referral_id=referral.id,
                amount_kopeks=reward.amount_kopeks,
                reason='referral_retention_reward',
            )
        )
        reward.status = ReferralRetentionRewardStatus.REWARDED.value
        reward.last_checked_at = now
        reward.completed_at = now
        reward.updated_at = now
        await db.commit()
        stats['rewarded'] += 1
        await _notify_reward(bot, referrer, referral, reward.amount_kopeks)

    if reward_ids:
        logger.info('Referral retention rewards processed', **stats)
    return stats
