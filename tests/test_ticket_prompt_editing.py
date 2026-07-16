import inspect
from unittest.mock import AsyncMock

from app.handlers import tickets


async def test_ticket_prompt_edits_caption_without_sending_new_message():
    bot = AsyncMock()
    markup = AsyncMock()

    result = await tickets._edit_ticket_prompt(
        bot,
        100,
        200,
        'Введите заголовок:',
        reply_markup=markup,
        is_caption=True,
    )

    assert result is True
    bot.edit_message_caption.assert_awaited_once_with(
        chat_id=100,
        message_id=200,
        caption='Введите заголовок:',
        reply_markup=markup,
        parse_mode='HTML',
    )
    bot.edit_message_text.assert_not_awaited()


async def test_ticket_prompt_edits_text_without_sending_new_message():
    bot = AsyncMock()
    markup = AsyncMock()

    result = await tickets._edit_ticket_prompt(
        bot,
        100,
        200,
        'Опишите проблему:',
        reply_markup=markup,
        is_caption=False,
    )

    assert result is True
    bot.edit_message_text.assert_awaited_once_with(
        chat_id=100,
        message_id=200,
        text='Опишите проблему:',
        reply_markup=markup,
        parse_mode='HTML',
    )
    bot.edit_message_caption.assert_not_awaited()


def test_ticket_creation_keeps_user_messages_and_reuses_bot_prompt():
    start_source = inspect.getsource(tickets.show_ticket_priority_selection)
    title_source = inspect.getsource(tickets.handle_ticket_title_input)
    message_source = inspect.getsource(tickets.handle_ticket_message_input)
    edit_source = inspect.getsource(tickets._edit_ticket_prompt)

    assert 'prompt_is_caption' in start_source
    assert 'callback.message.delete' not in start_source
    assert 'callback.message.answer' not in start_source

    for source in (title_source, message_source):
        assert '_try_delete_message_later' not in source
        assert 'message.answer' not in source
        assert '_edit_ticket_prompt' in source

    assert '.answer(' not in edit_source
    assert '.delete(' not in edit_source
