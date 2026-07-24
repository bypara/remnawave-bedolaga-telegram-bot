from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares.chat_type_filter import ChatTypeFilterMiddleware


def _callback(*, chat_id: int, user_id: int, data: str) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name='Admin')
    message = Message(
        message_id=1,
        date=0,
        chat=Chat(id=chat_id, type=ChatType.SUPERGROUP),
        from_user=user,
        text='notification',
    )
    return CallbackQuery(
        id='callback-id',
        from_user=user,
        chat_instance='chat-instance',
        message=message,
        data=data,
    )


@pytest.mark.asyncio
async def test_allows_admin_callback_from_configured_notification_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id = -100123456
    admin_id = 42
    monkeypatch.setattr(
        'app.middlewares.chat_type_filter.settings.ADMIN_NOTIFICATIONS_CHAT_ID',
        chat_id,
    )
    monkeypatch.setattr(
        'app.middlewares.chat_type_filter.settings.is_admin',
        lambda user_id: user_id == admin_id,
    )
    handler = AsyncMock(return_value='handled')
    event = _callback(
        chat_id=chat_id,
        user_id=admin_id,
        data='admin_withdrawal_approve_7',
    )

    result = await ChatTypeFilterMiddleware()(handler, event, {})

    assert result == 'handled'
    handler.assert_awaited_once_with(event, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('chat_id', 'user_id', 'data'),
    [
        (-100999999, 42, 'admin_withdrawal_approve_7'),
        (-100123456, 99, 'admin_withdrawal_approve_7'),
        (-100123456, 42, 'menu_subscription'),
    ],
)
async def test_still_drops_untrusted_group_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    chat_id: int,
    user_id: int,
    data: str,
) -> None:
    monkeypatch.setattr(
        'app.middlewares.chat_type_filter.settings.ADMIN_NOTIFICATIONS_CHAT_ID',
        -100123456,
    )
    monkeypatch.setattr(
        'app.middlewares.chat_type_filter.settings.is_admin',
        lambda candidate: candidate == 42,
    )
    handler = AsyncMock()
    event = _callback(chat_id=chat_id, user_id=user_id, data=data)

    result = await ChatTypeFilterMiddleware()(handler, event, {})

    assert result is None
    handler.assert_not_awaited()
