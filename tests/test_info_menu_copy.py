import json
from pathlib import Path


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_info_menu_header_uses_requested_custom_emoji_and_full_title():
    expected_titles = {'ru': 'Информация', 'en': 'Information'}

    for language, title in expected_titles.items():
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        value = locale['MENU_INFO_HEADER']

        assert 'emoji-id="5258474669769497337"' in value
        assert title in value
        assert 'ℹ️' not in value
        assert locale['MENU_INFO_PROMPT'] == ''
