import json
from pathlib import Path


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_post_registration_offer_uses_requested_custom_emoji_in_both_languages():
    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        value = locale['POST_REGISTRATION_OFFER']

        assert 'emoji-id="5461151367559141950"' in value
        assert '⚡' not in value
        assert '🛡' not in value
        assert '🌍' not in value


def test_post_registration_offer_contains_support_reassurance():
    ru = json.loads((BRAND_LOCALES / 'ru.json').read_text(encoding='utf-8'))
    en = json.loads((BRAND_LOCALES / 'en.json').read_text(encoding='utf-8'))

    assert 'напишите нам' in ru['POST_REGISTRATION_OFFER']
    assert 'message us' in en['POST_REGISTRATION_OFFER']
