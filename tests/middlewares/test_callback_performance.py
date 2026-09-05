import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, User as TgUser

from app.middlewares.auth import (
    LAST_ACTIVITY_UPDATE_INTERVAL,
    _is_lightweight_navigation,
    _should_refresh_last_activity,
)
from app.utils import photo_message
from app.utils.cache import ChannelSubCache, cache
from app.utils.callback_answer import answer_callback_in_background


def test_last_activity_is_refreshed_at_most_once_per_interval() -> None:
    now = datetime.now(UTC)

    assert _should_refresh_last_activity(None, now) is True
    assert _should_refresh_last_activity(now - LAST_ACTIVITY_UPDATE_INTERVAL + timedelta(seconds=1), now) is False
    assert _should_refresh_last_activity(now - LAST_ACTIVITY_UPDATE_INTERVAL, now) is True


def test_only_safe_navigation_uses_lightweight_user_loader() -> None:
    user = TgUser(id=123, is_bot=False, first_name='Test')

    assert _is_lightweight_navigation(CallbackQuery(id='1', from_user=user, chat_instance='x', data='menu_profile'))
    assert not _is_lightweight_navigation(
        CallbackQuery(id='2', from_user=user, chat_instance='x', data='subscription_confirm')
    )


@pytest.mark.asyncio
async def test_navigation_callback_answer_runs_in_background() -> None:
    release = asyncio.Event()
    callback = MagicMock()
    callback.answer = AsyncMock(side_effect=lambda: release.wait())

    answer_callback_in_background(callback)
    await asyncio.sleep(0)

    callback.answer.assert_awaited_once()
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_photo_navigation_edits_caption_without_replacing_media(monkeypatch) -> None:
    monkeypatch.setattr(photo_message.settings, 'ENABLE_LOGO_MODE', True)
    monkeypatch.setattr(photo_message, 'is_qr_message', lambda _message: False)

    message = MagicMock()
    message.photo = [MagicMock()]
    message.edit_caption = AsyncMock()
    message.edit_media = AsyncMock()
    callback = MagicMock(message=message)
    keyboard = MagicMock()

    await photo_message.edit_or_answer_photo(callback, 'Updated', keyboard)

    message.edit_caption.assert_awaited_once_with(
        caption='Updated',
        reply_markup=keyboard,
        parse_mode='HTML',
    )
    message.edit_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_reactivation_marker_uses_short_cache(monkeypatch) -> None:
    get = AsyncMock(return_value=1)
    set_value = AsyncMock(return_value=True)
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(cache, 'get', get)
    monkeypatch.setattr(cache, 'set', set_value)
    monkeypatch.setattr(cache, 'delete', delete)

    assert await ChannelSubCache.was_reactivation_checked_recently(123) is True
    await ChannelSubCache.mark_reactivation_checked(123)
    await ChannelSubCache.invalidate_reactivation_check(123)

    get.assert_awaited_once_with('channel_reactivation_checked:123')
    set_value.assert_awaited_once_with(
        'channel_reactivation_checked:123',
        1,
        expire=ChannelSubCache.REACTIVATION_CHECK_TTL,
    )
    delete.assert_awaited_once_with('channel_reactivation_checked:123')
