"""Regression tests for OIDC replay protection around the legal-consent challenge."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from app.cabinet.routes.auth import auth_telegram_oidc
from app.cabinet.schemas.auth import TelegramOIDCAuthRequest


def _oidc_claims() -> dict[str, object]:
    return {
        'id': 123456,
        'sub': '123456',
        'name': 'New User',
        'locale': 'ru',
        'exp': int(datetime.now(UTC).timestamp()) + 300,
    }


def _patch_oidc_prerequisites(stack: ExitStack) -> None:
    stack.enter_context(patch('app.cabinet.routes.auth.get_client_ip', return_value='1.2.3.4'))
    stack.enter_context(
        patch('app.cabinet.routes.auth.RateLimitCache.is_ip_rate_limited', AsyncMock(return_value=False))
    )
    stack.enter_context(patch('app.cabinet.routes.auth.get_setting_value', AsyncMock(side_effect=['true', '123456'])))
    stack.enter_context(
        patch('app.cabinet.routes.auth.validate_telegram_oidc_token', AsyncMock(return_value=_oidc_claims()))
    )
    stack.enter_context(patch('app.cabinet.routes.auth.get_user_by_telegram_id', AsyncMock(return_value=None)))


@pytest.mark.asyncio
async def test_legal_consent_challenge_does_not_consume_oidc_token() -> None:
    request = TelegramOIDCAuthRequest(id_token='valid-oidc-token')
    replay = AsyncMock(return_value=False)
    require_consent = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={'code': 'legal_consent_required'},
        )
    )

    with ExitStack() as stack:
        _patch_oidc_prerequisites(stack)
        stack.enter_context(patch('app.cabinet.routes.auth.TokenReplayCache.is_token_replayed', replay))
        stack.enter_context(patch('app.cabinet.routes.auth._require_legal_consent', require_consent))

        with pytest.raises(HTTPException) as exc:
            await auth_telegram_oidc(request=request, raw_request=MagicMock(), db=AsyncMock())

    assert exc.value.status_code == status.HTTP_428_PRECONDITION_REQUIRED
    assert require_consent.await_args.kwargs['allow_deferred'] is True
    replay.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_guard_still_runs_before_new_user_is_created() -> None:
    request = TelegramOIDCAuthRequest(
        id_token='already-used-oidc-token',
        accepted_legal_documents=['public_offer', 'privacy_policy'],
    )
    replay = AsyncMock(return_value=True)
    create_user = AsyncMock()

    with ExitStack() as stack:
        _patch_oidc_prerequisites(stack)
        stack.enter_context(patch('app.cabinet.routes.auth._require_legal_consent', AsyncMock(return_value=[])))
        stack.enter_context(patch('app.cabinet.routes.auth.TokenReplayCache.is_token_replayed', replay))
        stack.enter_context(patch('app.cabinet.routes.auth.create_user', create_user))

        with pytest.raises(HTTPException) as exc:
            await auth_telegram_oidc(request=request, raw_request=MagicMock(), db=AsyncMock())

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    replay.assert_awaited_once()
    create_user.assert_not_awaited()
