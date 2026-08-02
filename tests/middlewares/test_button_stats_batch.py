import asyncio
from unittest.mock import AsyncMock

import pytest

from app.middlewares.button_stats import ButtonClickBatchWriter, ButtonClickEvent


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
