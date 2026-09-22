"""HTTP boundary tests for signed, at-least-once Anore webhooks."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.config import settings
from app.webserver.payments import create_payment_router


SECRET = 'cashbox-secret'
PATH = '/anore-webhook'


class DummyBot:
    pass


@pytest.fixture(autouse=True)
def anore_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'ANORE_ENABLED', True, raising=False)
    monkeypatch.setattr(settings, 'ANORE_API_KEY', 'an_test_key', raising=False)
    monkeypatch.setattr(settings, 'ANORE_WEBHOOK_SECRET', SECRET, raising=False)
    monkeypatch.setattr(settings, 'ANORE_WEBHOOK_PATH', PATH, raising=False)


def _route(router, method: str = 'POST'):
    for route in router.routes:
        if getattr(route, 'path', '') == PATH and method in getattr(route, 'methods', set()):
            return route
    raise AssertionError('Anore route not mounted')


def _request(payload: dict, *, secret: str = SECRET, event_header: str | None = None, delivery: str | None = 'd-1'):
    raw = json.dumps(payload, separators=(',', ':')).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {
        'content-type': 'application/json',
        'anore-signature': signature,
        'anore-event': event_header or str(payload.get('event') or ''),
    }
    if delivery is not None:
        headers['anore-delivery-id'] = delivery
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'method': 'POST',
        'path': PATH,
        'headers': [(key.encode(), value.encode()) for key, value in headers.items()],
        'client': ('127.0.0.1', 12345),
    }

    async def receive() -> dict:
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    return Request(scope, receive)


def _payload(event: str = 'payment.succeeded') -> dict:
    return {
        'event': event,
        'id': 'e2dfaa6e-c423-4b5f-95b3-f203933d18f0',
        'orderId': 'an123_test',
        'status': 'paid',
    }


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_valid_webhook_is_acknowledged_and_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = AsyncMock(return_value=True)
    monkeypatch.setattr('app.webserver.payments._process_payment_service_callback', callback)
    router = create_payment_router(DummyBot(), SimpleNamespace())

    response = await _route(router).endpoint(_request(_payload()))
    await _drain()

    assert response.status_code == 200
    callback.assert_awaited_once()
    assert callback.await_args.args[1]['_delivery_id'] == 'd-1'
    assert callback.await_args.args[2] == 'process_anore_callback'


@pytest.mark.anyio
async def test_invalid_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = AsyncMock(return_value=True)
    monkeypatch.setattr('app.webserver.payments._process_payment_service_callback', callback)
    router = create_payment_router(DummyBot(), SimpleNamespace())

    response = await _route(router).endpoint(_request(_payload(), secret='wrong'))
    await _drain()

    assert response.status_code == 400
    callback.assert_not_awaited()


@pytest.mark.anyio
async def test_event_header_and_delivery_id_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = AsyncMock(return_value=True)
    monkeypatch.setattr('app.webserver.payments._process_payment_service_callback', callback)
    router = create_payment_router(DummyBot(), SimpleNamespace())

    mismatch = await _route(router).endpoint(_request(_payload(), event_header='payment.expired'))
    missing_delivery = await _route(router).endpoint(_request(_payload(), delivery=None))
    await _drain()

    assert mismatch.status_code == 400
    assert missing_delivery.status_code == 400
    callback.assert_not_awaited()


@pytest.mark.anyio
async def test_payout_event_is_ignored_but_acknowledged(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = AsyncMock(return_value=True)
    monkeypatch.setattr('app.webserver.payments._process_payment_service_callback', callback)
    router = create_payment_router(DummyBot(), SimpleNamespace())

    response = await _route(router).endpoint(_request(_payload('payout.succeeded')))
    await _drain()

    assert response.status_code == 200
    callback.assert_not_awaited()


def test_route_is_absent_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    router = create_payment_router(DummyBot(), SimpleNamespace())
    assert any(getattr(route, 'path', '') == PATH for route in router.routes)

    monkeypatch.setattr(settings, 'ANORE_WEBHOOK_SECRET', None, raising=False)
    router = create_payment_router(DummyBot(), SimpleNamespace())
    assert router is None or not any(getattr(route, 'path', '') == PATH for route in router.routes)
