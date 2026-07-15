import json
from pathlib import Path


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_balance_history_uses_requested_custom_emoji_in_both_languages():
    expected = {
        'BALANCE_HISTORY_TITLE': '5244837092042750681',
        'BALANCE_HISTORY_AMOUNT': '5258204546391351475',
        'BALANCE_HISTORY_OPERATION': '5258328383183396223',
        'BALANCE_HISTORY_DATE': '5258105663359294787',
    }

    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        for key, emoji_id in expected.items():
            assert f'emoji-id="{emoji_id}"' in locale[key]


def test_balance_history_templates_keep_dynamic_values():
    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        assert '{amount}' in locale['BALANCE_HISTORY_AMOUNT']
        assert '{operation}' in locale['BALANCE_HISTORY_OPERATION']
        assert '{date}' in locale['BALANCE_HISTORY_DATE']
