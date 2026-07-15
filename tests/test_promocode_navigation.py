from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import menu


@pytest.mark.asyncio
async def test_back_from_promocode_clears_fsm_before_showing_profile(monkeypatch):
    callback = AsyncMock()
    state = AsyncMock()
    render_profile = AsyncMock()
    monkeypatch.setattr(menu, 'edit_or_answer_photo', render_profile)

    user = SimpleNamespace(
        language='ru',
        username='tester',
        full_name='Tester',
        balance_kopeks=0,
    )

    await menu.show_profile_menu(callback, user, state)

    state.clear.assert_awaited_once()
    render_profile.assert_awaited_once()
    callback.answer.assert_awaited_once()
