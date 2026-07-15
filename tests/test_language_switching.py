from pathlib import Path

from app.keyboards.inline import get_interface_languages, get_language_selection_keyboard


def test_fork_language_keyboard_contains_only_ru_and_en():
    keyboard = get_language_selection_keyboard(current_language='ru')
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert get_interface_languages() == ['ru', 'en']
    assert [button.callback_data for button in buttons] == ['language_select:ru', 'language_select:en']
    assert [button.text for button in buttons] == ['✅ 🇷🇺 Русский', '🇬🇧 English']


def test_profile_language_callback_is_not_limited_to_empty_fsm_state():
    source_path = Path(__file__).resolve().parents[1] / 'app' / 'handlers' / 'menu.py'
    source = source_path.read_text(encoding='utf-8')
    registration = "dp.callback_query.register(process_language_change, F.data.startswith('language_select:'))"

    assert registration in source
