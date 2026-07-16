import json
import re
from pathlib import Path

from app.localization.loader import clear_locale_cache, load_locale


BRAND_LOCALES_DIR = Path(__file__).resolve().parents[1] / 'app' / 'localization' / 'brand_locales'
PLACEHOLDER_RE = re.compile(r'\{[^}]+\}')


def test_brand_locales_have_matching_keys_and_placeholders():
    ru = json.loads((BRAND_LOCALES_DIR / 'ru.json').read_text(encoding='utf-8'))
    en = json.loads((BRAND_LOCALES_DIR / 'en.json').read_text(encoding='utf-8'))

    assert set(ru) == set(en)
    for key, ru_value in ru.items():
        assert sorted(PLACEHOLDER_RE.findall(ru_value)) == sorted(PLACEHOLDER_RE.findall(en[key])), key


def test_brand_locale_wins_over_runtime_locale_overrides():
    clear_locale_cache()
    try:
        ru = load_locale('ru')
        assert ru['MAIN_MENU'] == '<tg-emoji emoji-id="5255850874248399164">🎁</tg-emoji>'
        assert ru['MAIN_MENU_ACTION_PROMPT'] == ''
    finally:
        clear_locale_cache()
