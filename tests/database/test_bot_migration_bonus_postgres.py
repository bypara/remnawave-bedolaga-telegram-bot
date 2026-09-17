"""Migration credit concurrency/atomicity must be verified on real PostgreSQL."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database.models import BotMigrationClaim, Transaction, User, UserStatus
from app.services.bot_migration_service import claim_migration_bonus, extract_migration_token, issue_migration_link
from tests.fixtures.postgres_db import postgres_sessions


pytestmark = pytest.mark.postgres
TABLES = [User.__table__, BotMigrationClaim.__table__, Transaction.__table__]
OLD_BOT_ID = 123456
NEW_BOT_ID = 654321
TARGET = 'new_service_bot'


@pytest.fixture(autouse=True)
def bonus_settings(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', True)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_AMOUNT_RUBLES', 75.50)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', f'https://t.me/{TARGET}')


async def seed(db, telegram_id=10001, status=UserStatus.ACTIVE.value):
    user = User(telegram_id=telegram_id, first_name='Test', status=status, balance_kopeks=1200)
    db.add(user)
    await db.commit()
    return user


def token_from(link):
    payload = parse_qs(urlsplit(link.url).query)['start'][0]
    assert len(payload) <= 64
    return extract_migration_token(payload)


async def test_issue_does_not_credit_and_claim_credits_once(postgres_database):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db)
        link = await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)
        token = token_from(link)
        assert link.amount_kopeks == 7550
        await db.refresh(user)
        assert user.balance_kopeks == 1200
        first = await claim_migration_bonus(db, token, user.telegram_id, NEW_BOT_ID, TARGET)
        second = await claim_migration_bonus(db, token, user.telegram_id, NEW_BOT_ID, TARGET)
        assert first.status == 'credited'
        assert second.status == 'already_claimed'
        await db.refresh(user)
        assert user.balance_kopeks == 8750
        transactions = (await db.execute(select(Transaction))).scalars().all()
        assert len(transactions) == 1
        assert transactions[0].amount_kopeks == 7550
        assert transactions[0].payment_method == 'manual'
        assert transactions[0].external_id == f'bot_migration_bonus:{user.id}'
        claim = await db.get(BotMigrationClaim, user.id)
        assert claim.claimed_at is not None


async def test_forwarded_token_wrong_bot_and_unknown_token_do_not_credit(postgres_database):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        owner = await seed(db)
        recipient = await seed(db, telegram_id=10002)
        token = token_from(await issue_migration_link(db, owner.telegram_id, OLD_BOT_ID))
        for telegram_id, bot_id, username, value in [
            (recipient.telegram_id, NEW_BOT_ID, TARGET, token),
            (owner.telegram_id, OLD_BOT_ID, TARGET, token),
            (owner.telegram_id, NEW_BOT_ID, 'wrong_bot', token),
            (owner.telegram_id, NEW_BOT_ID, TARGET, 'x' * 43),
            (99999, NEW_BOT_ID, TARGET, token),
        ]:
            result = await claim_migration_bonus(db, value, telegram_id, bot_id, username)
            assert result.status == 'invalid'
        await db.refresh(owner)
        await db.refresh(recipient)
        assert owner.balance_kopeks == recipient.balance_kopeks == 1200
        assert (await db.scalar(select(func.count()).select_from(Transaction))) == 0


@pytest.mark.parametrize('status', [UserStatus.BLOCKED.value, UserStatus.DELETED.value])
async def test_ineligible_users_never_get_bonus_link(postgres_database, status):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db, status=status)
        link = await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)
        assert link.amount_kopeks == 0
        assert link.url == settings.BOT_MIGRATION_URL
        assert await db.get(BotMigrationClaim, user.id) is None
        unknown = await issue_migration_link(db, 99999, OLD_BOT_ID)
        assert unknown.amount_kopeks == 0


async def test_disabling_bonus_prevents_issue_and_claim(postgres_database, monkeypatch):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db)
        token = token_from(await issue_migration_link(db, user.telegram_id, OLD_BOT_ID))
        monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', False)
        assert (await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)).amount_kopeks == 0
        assert (await claim_migration_bonus(db, token, user.telegram_id, NEW_BOT_ID, TARGET)).status == 'disabled'
        await db.refresh(user)
        assert user.balance_kopeks == 1200


async def test_account_blocked_after_issue_cannot_claim_from_stale_auth_session(postgres_database):
    async with postgres_sessions(postgres_database, TABLES, count=2) as (owner, admin):
        user = await seed(owner)
        telegram_id = user.telegram_id
        token = token_from(await issue_migration_link(owner, telegram_id, OLD_BOT_ID))
        other = await admin.get(User, user.id)
        other.status = UserStatus.BLOCKED.value
        await admin.commit()
        assert user.status == UserStatus.ACTIVE.value
        result = await claim_migration_bonus(owner, token, telegram_id, NEW_BOT_ID, TARGET)
        assert result.status == 'invalid'
        assert await owner.scalar(select(func.count()).select_from(Transaction)) == 0


async def test_amount_changes_keep_promises_and_cannot_reset_claim(postgres_database, monkeypatch):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db)
        original = await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)
        token = token_from(original)
        monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_AMOUNT_RUBLES', 125)
        repeated = await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)
        assert repeated == original
        newcomer = await seed(db, telegram_id=10002)
        assert (await issue_migration_link(db, newcomer.telegram_id, OLD_BOT_ID)).amount_kopeks == 12500
        result = await claim_migration_bonus(db, token, user.telegram_id, NEW_BOT_ID, TARGET)
        assert result.amount_kopeks == 7550
        assert (await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)).amount_kopeks == 0


async def test_target_change_invalidates_old_link_without_resetting_claim(postgres_database, monkeypatch):
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db)
        old = token_from(await issue_migration_link(db, user.telegram_id, OLD_BOT_ID))
        monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/other_service_bot')
        assert (await claim_migration_bonus(db, old, user.telegram_id, NEW_BOT_ID, TARGET)).status == 'invalid'
        fresh = token_from(await issue_migration_link(db, user.telegram_id, OLD_BOT_ID))
        assert fresh != old
        assert (
            await claim_migration_bonus(db, old, user.telegram_id, NEW_BOT_ID, 'other_service_bot')
        ).status == 'invalid'
        assert (
            await claim_migration_bonus(db, fresh, user.telegram_id, NEW_BOT_ID, 'other_service_bot')
        ).status == 'credited'
        monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', f'https://t.me/{TARGET}')
        assert (await issue_migration_link(db, user.telegram_id, OLD_BOT_ID)).amount_kopeks == 0


async def test_concurrent_starts_credit_once(postgres_database):
    async with postgres_sessions(postgres_database, TABLES, count=3) as (first, second, watcher):
        user = await seed(first)
        telegram_id = user.telegram_id
        user_id = user.id
        token = token_from(await issue_migration_link(first, telegram_id, OLD_BOT_ID))
        results = await asyncio.gather(
            claim_migration_bonus(first, token, telegram_id, NEW_BOT_ID, TARGET),
            claim_migration_bonus(second, token, telegram_id, NEW_BOT_ID, TARGET),
        )
        assert sorted(result.status for result in results) == ['already_claimed', 'credited']
        await first.rollback()
        await second.rollback()
        assert await watcher.scalar(select(User.balance_kopeks).where(User.id == user_id)) == 8750
        assert await watcher.scalar(select(func.count()).select_from(Transaction)) == 1


async def test_concurrent_issue_reuses_one_personal_token(postgres_database):
    async with postgres_sessions(postgres_database, TABLES, count=2) as (first, second):
        user = await seed(first)
        telegram_id = user.telegram_id
        links = await asyncio.gather(
            issue_migration_link(first, telegram_id, OLD_BOT_ID),
            issue_migration_link(second, telegram_id, OLD_BOT_ID),
        )
        assert links[0] == links[1]


async def test_ledger_failure_rolls_back_balance_and_marker_then_retries(postgres_database, monkeypatch):
    import app.services.bot_migration_service as service

    real_create = service.create_transaction
    async with postgres_sessions(postgres_database, TABLES, count=1) as (db,):
        user = await seed(db)
        telegram_id, user_id = user.telegram_id, user.id
        token = token_from(await issue_migration_link(db, telegram_id, OLD_BOT_ID))

        async def fail(*args, **kwargs):
            raise RuntimeError('Simulated transaction write failure')

        monkeypatch.setattr(service, 'create_transaction', fail)
        with pytest.raises(RuntimeError, match='Simulated'):
            await claim_migration_bonus(db, token, telegram_id, NEW_BOT_ID, TARGET)
        assert await db.scalar(select(User.balance_kopeks).where(User.id == user_id)) == 1200
        claim = await db.get(BotMigrationClaim, user_id)
        assert claim.claimed_at is None
        assert await db.scalar(select(func.count()).select_from(Transaction)) == 0
        monkeypatch.setattr(service, 'create_transaction', real_create)
        assert (await claim_migration_bonus(db, token, telegram_id, NEW_BOT_ID, TARGET)).status == 'credited'
