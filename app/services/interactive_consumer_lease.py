"""Redis lease prevents two interactive consumers taking one Telegram token."""

import asyncio
from uuid import uuid4

import structlog

from app.utils.redis_client import create_redis


logger = structlog.get_logger(__name__)
_RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class InteractiveConsumerLease:
    ttl = 60
    renew_interval = 15

    def __init__(self, bot_id: int):
        self.key = f'bot:interactive:consumer:{bot_id}'
        self.owner = uuid4().hex
        self.redis = None
        self.task = None
        self.parent = None
        self.lost = False

    async def __aenter__(self):
        self.redis = create_redis()
        try:
            await self.redis.ping()
            acquired = await self.redis.set(self.key, self.owner, ex=self.ttl, nx=True)
            if not acquired:
                raise RuntimeError('Для этого Telegram-токена уже работает интерактивный consumer')
            self.parent = asyncio.current_task()
            self.task = asyncio.create_task(self._renew(), name='interactive-consumer-lease')
            return self
        except BaseException:
            await self.redis.aclose()
            raise

    async def _renew(self):
        while True:
            await asyncio.sleep(self.renew_interval)
            try:
                renewed = await self.redis.eval(_RENEW, 1, self.key, self.owner, self.ttl)
                if renewed:
                    continue
            except Exception:
                pass
            self.lost = True
            logger.error('Потеряна блокировка интерактивного consumer, процесс будет остановлен')
            if self.parent:
                self.parent.cancel()
            return

    async def __aexit__(self, exc_type, exc, traceback):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            await self.redis.eval(_RELEASE, 1, self.key, self.owner)
        except Exception:
            logger.warning('Не удалось снять блокировку consumer; она истечёт автоматически')
        finally:
            await self.redis.aclose()
        if self.lost:
            raise RuntimeError('Интерактивный consumer остановлен из-за потери Redis lease') from exc
