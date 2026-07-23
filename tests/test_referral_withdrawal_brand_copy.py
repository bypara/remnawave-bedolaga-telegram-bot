import json
from pathlib import Path


BRAND_LOCALES_DIR = Path(__file__).resolve().parents[1] / 'app' / 'localization' / 'brand_locales'


def _locales():
    return {
        language: json.loads((BRAND_LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
        for language in ('ru', 'en')
    }


def test_referral_withdrawal_copy_uses_requested_custom_emoji():
    for locale in _locales().values():
        assert 'emoji-id="5409048419211682843"' in locale['REFERRAL_WITHDRAWAL_TITLE']
        assert 'emoji-id="5334544901428229844"' in locale['REFERRAL_WITHDRAWAL_ONLY_REF_MODE']
        assert 'emoji-id="5210952531676504517"' in locale['REFERRAL_WITHDRAWAL_MIN_AVAILABLE_ERROR']


def test_referral_withdrawal_copy_renders_dynamic_values():
    samples = {
        'REFERRAL_WITHDRAWAL_STATS_EARNED': {'amount': '100 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_SPENT': {'amount': '20 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_WITHDRAWN': {'amount': '30 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_AVAILABLE': {'amount': '50 ₽'},
        'REFERRAL_WITHDRAWAL_MIN_AMOUNT': {'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_COOLDOWN': {'days': 5},
        'REFERRAL_WITHDRAWAL_MIN_AVAILABLE_ERROR': {'minimum': '500 ₽', 'available': '50 ₽'},
    }

    for locale in _locales().values():
        for key, values in samples.items():
            rendered = locale[key].format(**values)
            assert '{' not in rendered
            assert '}' not in rendered
