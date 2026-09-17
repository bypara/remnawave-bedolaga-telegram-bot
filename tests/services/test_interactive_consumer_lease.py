import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import interactive_consumer_lease as lease_module


def redis_client(acquired=True):
    return SimpleNamespace(
        ping=AsyncMock(), set=AsyncMock(return_value=acquired), eval=AsyncMock(return_value=1), aclose=AsyncMock()
    )


async def test_single_consumer_lease_atomic_and_owner_scoped(monkeypatch):
    redis = redis_client()
    monkeypatch.setattr(lease_module, 'create_redis', lambda: redis)
    lease = lease_module.InteractiveConsumerLease(456)
    async with lease:
        redis.set.assert_awaited_once_with(lease.key, lease.owner, ex=60, nx=True)
        assert lease.task is not None
    redis.eval.assert_awaited_once_with(lease_module._RELEASE, 1, lease.key, lease.owner)
    redis.aclose.assert_awaited_once()
    assert lease.task.done()


async def test_second_consumer_refused_without_removing_owner_lock(monkeypatch):
    redis = redis_client(False)
    monkeypatch.setattr(lease_module, 'create_redis', lambda: redis)
    with pytest.raises(RuntimeError, match='уже работает'):
        async with lease_module.InteractiveConsumerLease(456):
            pytest.fail('Duplicate consumer accepted')
    redis.eval.assert_not_awaited()
    redis.aclose.assert_awaited_once()


async def test_lease_loss_stops_parent_before_releasing(monkeypatch):
    redis = redis_client()
    redis.eval.return_value = 0
    monkeypatch.setattr(lease_module, 'create_redis', lambda: redis)
    lease = lease_module.InteractiveConsumerLease(456)
    lease.renew_interval = 0.001
    with pytest.raises(RuntimeError, match='потери Redis'):
        async with lease:
            await asyncio.Event().wait()
    assert lease.lost
    redis.aclose.assert_awaited_once()
