"""REST client and webhook verification for Anore payments."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import aiohttp
import structlog

from app.config import settings


logger = structlog.get_logger(__name__)


class AnoreAPIError(Exception):
    """Anore returned a non-success HTTP response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f'Anore API error ({status_code}): {message}')


class AnoreNetworkError(Exception):
    """The request outcome is unknown because no response was received."""


class AnoreService:
    """Minimal client for ``https://api.anore.cc/v1``."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        return (settings.ANORE_BASE_URL or 'https://api.anore.cc/v1').rstrip('/')

    @property
    def api_key(self) -> str:
        return settings.ANORE_API_KEY or ''

    @property
    def webhook_secret(self) -> str:
        return settings.ANORE_WEBHOOK_SECRET or ''

    @property
    def is_test_key(self) -> bool:
        return self.api_key.startswith('an_test_')

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _headers(self, raw_body: bytes | None = None) -> dict[str, str]:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        if raw_body is not None and self.webhook_secret:
            headers['Anore-Signature'] = hmac.new(
                self.webhook_secret.encode('utf-8'),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
        return headers

    @staticmethod
    def _error_message(data: Any) -> str:
        if isinstance(data, dict):
            for key in ('message', 'error', 'detail'):
                if data.get(key):
                    return str(data[key])
        return str(data)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f'{self.base_url}/{path.lstrip("/")}'
        raw_body = None
        if payload is not None:
            raw_body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

        try:
            session = await self._get_session()
            async with session.request(
                method,
                url,
                data=raw_body,
                headers=self._headers(raw_body),
            ) as response:
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    data = {'message': await response.text()}

                if response.status >= 400:
                    message = self._error_message(data)
                    logger.error('Anore API error', status=response.status, url=url, message=message)
                    raise AnoreAPIError(response.status, message)

                if not isinstance(data, dict):
                    raise AnoreAPIError(response.status, 'Anore returned a non-object JSON response')
                return data
        except AnoreAPIError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            logger.error('Anore API connection error', url=url, error=str(error))
            raise AnoreNetworkError(str(error)) from error

    async def create_payment(
        self,
        *,
        amount_kopeks: int,
        description: str,
        order_id: str,
        email: str | None = None,
        methods: str | None = None,
        success_url: str | None = None,
        fail_url: str | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'amount': float(Decimal(amount_kopeks) / Decimal(100)),
            'currency': 'RUB',
            'description': description[:255],
            'orderId': order_id[:64],
        }
        if settings.ANORE_SHOP_ID is not None:
            payload['shopId'] = settings.ANORE_SHOP_ID
        if email:
            payload['email'] = email
        if methods:
            payload['methods'] = methods
        if success_url:
            payload['successurl'] = success_url
            payload['getbackurl'] = success_url
        if fail_url:
            payload['failurl'] = fail_url
        if callback_url:
            payload['callbackUrl'] = callback_url

        data = await self._request('POST', '/payments', payload=payload)
        if not data.get('success') or not data.get('id') or not data.get('paymentUrl'):
            logger.error('Anore create_payment: incomplete response', order_id=order_id, response_data=data)
            raise AnoreAPIError(200, 'Incomplete create payment response')
        return data

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request('GET', f'/payments/{payment_id}')

    def verify_webhook_signature(self, raw_body: bytes, signature: str | None) -> bool:
        """Verify ``Anore-Signature = HMAC-SHA256(raw body, cashbox SECRET)``."""
        secret = self.webhook_secret
        received = (signature or '').strip().lower()
        if not secret or not received:
            logger.warning('Anore webhook signature or secret is missing')
            return False
        expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)


anore_service = AnoreService()
