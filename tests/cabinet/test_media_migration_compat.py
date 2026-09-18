from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from fastapi import HTTPException

from app.cabinet.routes import media
from app.config import settings


FILE_ID = 'BAADAgADabcdef_-1234567890'


def unavailable():
    return TelegramBadRequest(method=None, message='wrong file_id or the file is temporarily unavailable')


def fake_bot():
    return SimpleNamespace(
        get_file=AsyncMock(return_value=SimpleNamespace(file_path='photos/file.jpg')),
        download_file=AsyncMock(return_value=BytesIO(b'image')),
        session=SimpleNamespace(close=AsyncMock()),
    )


@pytest.fixture
def bots(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_TOKEN', 'current-token')
    monkeypatch.setattr(settings, 'LEGACY_BOT_TOKEN', 'legacy-token')
    current, legacy = fake_bot(), fake_bot()
    create = Mock(side_effect=[current, legacy])
    monkeypatch.setattr(media, 'create_bot', create)
    return current, legacy, create


async def download(sender='current', token=None):
    return await media.download_media(
        FILE_ID, media.make_media_token(FILE_ID, sender) if token is None else token, sender
    )


async def test_old_attachment_retries_legacy_and_preserves_security_headers(bots):
    current, legacy, create = bots
    current.get_file.side_effect = unavailable()
    response = await download()
    assert response.body == b'image'
    assert response.media_type == 'image/jpeg'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'sandbox' in response.headers['content-security-policy']
    assert create.call_count == 2
    create.assert_called_with(token='legacy-token')
    current.download_file.assert_not_awaited()
    legacy.get_file.assert_awaited_once_with(FILE_ID)
    legacy.download_file.assert_awaited_once_with('photos/file.jpg')
    current.session.close.assert_awaited_once()
    legacy.session.close.assert_awaited_once()


async def test_new_attachment_does_not_touch_legacy(bots):
    current, legacy, create = bots
    assert (await download()).body == b'image'
    create.assert_called_once_with()
    current.session.close.assert_awaited_once()
    legacy.get_file.assert_not_awaited()


@pytest.mark.parametrize('token', ['', 'invalid', 'other-file', 'wrong-sender', 'expired'])
async def test_invalid_authorization_never_contacts_either_bot(bots, token):
    if token == 'other-file':
        token = media.make_media_token(FILE_ID + 'x')
    elif token == 'wrong-sender':
        token = media.make_media_token(FILE_ID, 'legacy')
    elif token == 'expired':
        token = f'1.{media._media_signature(FILE_ID, 1)}'
    with pytest.raises(HTTPException) as exc:
        await download(token=token)
    assert exc.value.status_code == 404
    bots[2].assert_not_called()


@pytest.mark.parametrize('legacy_token', [None, 'current-token'])
async def test_missing_or_identical_legacy_token_returns_404(monkeypatch, bots, legacy_token):
    monkeypatch.setattr(settings, 'LEGACY_BOT_TOKEN', legacy_token)
    bots[0].get_file.side_effect = unavailable()
    with pytest.raises(HTTPException) as exc:
        await download()
    assert exc.value.status_code == 404
    bots[2].assert_called_once_with()
    bots[0].session.close.assert_awaited_once()


async def test_both_bots_reject_file_without_error_alert(bots, monkeypatch):
    current, legacy, _ = bots
    current.get_file.side_effect = legacy.get_file.side_effect = unavailable()
    error_log = Mock()
    monkeypatch.setattr(media.logger, 'error', error_log)
    with pytest.raises(HTTPException) as exc:
        await download()
    assert exc.value.status_code == 404
    error_log.assert_not_called()
    current.session.close.assert_awaited_once()
    legacy.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    'error',
    [TelegramBadRequest(method=None, message='unrelated error'), TelegramNetworkError(method=None, message='timeout')],
)
async def test_other_failures_do_not_switch_bot(bots, error):
    bots[0].get_file.side_effect = error
    with pytest.raises(HTTPException) as exc:
        await download()
    assert exc.value.status_code == 500
    bots[2].assert_called_once_with()
    bots[0].session.close.assert_awaited_once()


async def test_explicit_legacy_sender_does_not_fallback_to_current(bots):
    bots[0].get_file.side_effect = unavailable()
    with pytest.raises(HTTPException) as exc:
        await download('legacy')
    assert exc.value.status_code == 404
    bots[2].assert_called_once_with(token='legacy-token')


async def test_legacy_download_failure_closes_both_sessions(bots):
    bots[0].get_file.side_effect = unavailable()
    bots[1].download_file.side_effect = TelegramNetworkError(method=None, message='timeout')
    with pytest.raises(HTTPException) as exc:
        await download()
    assert exc.value.status_code == 500
    bots[0].session.close.assert_awaited_once()
    bots[1].session.close.assert_awaited_once()
