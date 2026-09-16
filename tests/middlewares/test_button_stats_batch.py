import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.models import Base, ButtonClickLog, User
from app.middlewares.button_stats import ButtonClickBatchWriter, ButtonClickEvent
from tests.fixtures.sqlite_memory import memory_session


@pytest.mark.asyncio
async def test_clicks_are_written_in_one_batch() -> None:
    writer = ButtonClickBatchWriter(max_batch_size=10, flush_interval=0.01)
    writer._write_batch = AsyncMock()

    for index in range(3):
        writer.enqueue(
            ButtonClickEvent(
                button_id=f'menu_{index}',
                user_telegram_id=123,
                callback_data=f'menu_{index}',
                button_type='builtin',
                button_text=None,
            )
        )

    await asyncio.wait_for(writer.queue.join(), timeout=1)

    writer._write_batch.assert_awaited_once()
    assert len(writer._write_batch.await_args.args[0]) == 3
    writer._worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer._worker_task


@pytest.mark.asyncio
async def test_batch_resolves_only_telegram_ids(monkeypatch) -> None:
    async with memory_session(monkeypatch, list(Base.metadata.sorted_tables)) as db:
        db.add_all(
            [
                User(
                    id=555,
                    telegram_id=111,
                    first_name='A',
                    status='active',
                    language='ru',
                    balance_kopeks=0,
                    created_at=datetime.now(UTC),
                ),
                User(
                    id=1,
                    telegram_id=555,
                    first_name='B',
                    status='active',
                    language='ru',
                    balance_kopeks=0,
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()
        monkeypatch.setattr(
            'app.middlewares.button_stats.AsyncSessionLocal', async_sessionmaker(db.bind, expire_on_commit=False)
        )
        writer = ButtonClickBatchWriter()
        await writer._write_batch(
            [
                ButtonClickEvent('known', 555, None, 'payment', None),
                ButtonClickEvent('unknown', 999, None, 'message', 'text'),
            ]
        )
        rows = (await db.execute(select(ButtonClickLog).order_by(ButtonClickLog.id))).scalars().all()
        assert [(row.button_id, row.user_id) for row in rows] == [('known', 1), ('unknown', None)]
