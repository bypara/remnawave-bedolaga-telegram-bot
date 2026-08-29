"""Resend HTTPS transport: payload compatibility, retries and failures."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Self

import httpx
import pytest

from app.cabinet.services.email_service import EmailService
from app.config import settings


class _FakeClient:
    def __init__(self, results: Iterable[httpx.Response | Exception]) -> None:
        self.results = iter(results)
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        self.requests.append({'url': url, 'headers': dict(headers), 'json': json})
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def resend_ready(monkeypatch):
    monkeypatch.setattr(settings, 'EMAIL_PROVIDER', 'resend')
    monkeypatch.setattr(settings, 'RESEND_API_KEY', 're_test_secret')
    monkeypatch.setattr(settings, 'RESEND_API_URL', 'https://api.resend.test/emails')
    monkeypatch.setattr(settings, 'EMAIL_SEND_MAX_ATTEMPTS', 3)
    monkeypatch.setattr(settings, 'EMAIL_SEND_RETRY_BASE_SECONDS', 0.0)
    monkeypatch.setattr(settings, 'SMTP_FROM_EMAIL', 'noreply@mail.example.com')
    monkeypatch.setattr(settings, 'SMTP_FROM_NAME', 'Example VPN')
    monkeypatch.setattr(settings, 'SMTP_REPLY_TO', 'help@example.com')


def _response(status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request('POST', 'https://api.resend.test/emails'),
    )


def _install_client(monkeypatch, results: list[httpx.Response | Exception]) -> _FakeClient:
    fake = _FakeClient(results)
    monkeypatch.setattr(httpx, 'Client', lambda **_kwargs: fake)
    return fake


def test_resend_sends_existing_rendered_content_and_headers(monkeypatch, resend_ready):
    fake = _install_client(monkeypatch, [_response(200, {'id': 'email_123'})])
    service = EmailService()

    assert service.send_email(
        to_email='user@example.com',
        subject='Hello',
        body_html='<p>Hello</p>',
        attachments=[('receipt.pdf', b'pdf-bytes', 'application/pdf')],
        unsubscribe_url='https://app.example.com/unsubscribe/token',
    )

    request = fake.requests[0]
    assert request['url'] == 'https://api.resend.test/emails'
    assert request['headers']['Authorization'] == 'Bearer re_test_secret'
    assert request['headers']['Idempotency-Key']
    assert request['json']['from'] == 'Example VPN <noreply@mail.example.com>'
    assert request['json']['to'] == ['user@example.com']
    assert request['json']['reply_to'] == 'help@example.com'
    assert request['json']['text'] == 'Hello'
    assert request['json']['headers']['List-Unsubscribe-Post'] == 'List-Unsubscribe=One-Click'
    assert request['json']['attachments'] == [
        {
            'filename': 'receipt.pdf',
            'content': 'cGRmLWJ5dGVz',
            'content_type': 'application/pdf',
        }
    ]


def test_resend_retries_temporary_failure_with_same_idempotency_key(monkeypatch, resend_ready):
    fake = _install_client(
        monkeypatch,
        [
            _response(503, {'message': 'temporary'}),
            _response(200, {'id': 'email_after_retry'}),
        ],
    )

    assert EmailService().send_email('user@example.com', 'Hello', '<p>Hello</p>')
    assert len(fake.requests) == 2
    assert fake.requests[0]['headers']['Idempotency-Key'] == fake.requests[1]['headers']['Idempotency-Key']


def test_resend_does_not_retry_permanent_validation_error(monkeypatch, resend_ready):
    fake = _install_client(monkeypatch, [_response(422, {'message': 'invalid from'})])

    assert EmailService().send_email('user@example.com', 'Hello', '<p>Hello</p>') is False
    assert len(fake.requests) == 1


def test_resend_retries_network_errors_then_returns_false(monkeypatch, resend_ready):
    request = httpx.Request('POST', 'https://api.resend.test/emails')
    fake = _install_client(
        monkeypatch,
        [
            httpx.ConnectError('offline', request=request),
            httpx.ReadTimeout('timeout', request=request),
            httpx.ConnectError('offline', request=request),
        ],
    )

    assert EmailService().send_email('user@example.com', 'Hello', '<p>Hello</p>') is False
    assert len(fake.requests) == 3


def test_resend_requires_key_and_sender(monkeypatch, resend_ready):
    monkeypatch.setattr(settings, 'RESEND_API_KEY', '')
    assert EmailService().is_configured() is False
