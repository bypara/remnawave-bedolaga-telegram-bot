from app.handlers.start import _format_registration_rules_text, _get_language_prompt_text
from app.keyboards.inline import get_privacy_policy_keyboard, get_rules_keyboard
from app.localization.texts import get_texts


def test_language_prompt_uses_requested_custom_emoji():
    prompt = _get_language_prompt_text()

    assert 'emoji-id="5447410659077661506"' in prompt
    assert 'Выберите язык / Choose your language:' in prompt


def test_registration_rules_have_branded_header_without_duplicate_heading():
    texts = get_texts('ru')
    result = _format_registration_rules_text('📋 Правила использования Сервиса\n\nТекст правил', texts)

    assert result.startswith('<tg-emoji emoji-id="5282843764451195532">🖥</tg-emoji>')
    assert result.count('Правила использования') == 1
    assert result.endswith('Текст правил')


def test_legal_consent_buttons_use_requested_custom_emojis():
    for language in ('ru', 'en'):
        rules_buttons = get_rules_keyboard(language).inline_keyboard[0]
        privacy_buttons = get_privacy_policy_keyboard(language).inline_keyboard[0]

        assert rules_buttons[0].icon_custom_emoji_id == '5206607081334906820'
        assert rules_buttons[1].icon_custom_emoji_id == '5210952531676504517'
        assert privacy_buttons[0].icon_custom_emoji_id == '5206607081334906820'
        assert privacy_buttons[1].icon_custom_emoji_id == '5210952531676504517'
        assert all(not button.text.startswith(('✅', '❌')) for button in (*rules_buttons, *privacy_buttons))
