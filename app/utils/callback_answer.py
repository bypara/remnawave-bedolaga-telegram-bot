"""Helpers for acknowledging safe navigation callbacks without blocking rendering."""

import asyncio

import structlog
from aiogram.types import CallbackQuery


logger = structlog.get_logger(__name__)
_pending_answers: set[asyncio.Task[None]] = set()


async def _answer_callback(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except Exception as error:
        # A callback can expire while another Telegram request is in flight.
        # Navigation rendering must not fail only because the spinner could not
        # be dismissed anymore.
        logger.debug('Could not acknowledge navigation callback', error=str(error))


def answer_callback_in_background(callback: CallbackQuery) -> None:
    """Start callback acknowledgement in parallel with the message edit."""
    task = asyncio.create_task(_answer_callback(callback))
    _pending_answers.add(task)
    task.add_done_callback(_pending_answers.discard)
