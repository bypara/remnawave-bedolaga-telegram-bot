import json
from pathlib import Path


BRAND_LOCALES_DIR = Path(__file__).resolve().parents[1] / 'app' / 'localization' / 'brand_locales'


def _locales():
    return {
        language: json.loads((BRAND_LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
        for language in ('ru', 'en')
    }


def test_referral_withdrawal_copy_uses_requested_custom_emoji():
    expected = {
        'REFERRAL_WITHDRAWAL_READY': '5206607081334906820',
        'REFERRAL_WITHDRAWAL_ENTER_AMOUNT': '5409048419211682843',
        'REFERRAL_WITHDRAWAL_ENTER_DETAILS': '5431609822288033666',
        'REFERRAL_WITHDRAWAL_CONFIRM_TITLE': '5314504236132747481',
        'REFERRAL_WITHDRAWAL_CONFIRM_DETAILS': '5395444784611480792',
        'REFERRAL_WITHDRAWAL_CONFIRM_WARNING': '5436113877181941026',
        'REFERRAL_WITHDRAWAL_SUCCESS': '5206607081334906820',
        'REFERRAL_WITHDRAWAL_APPROVED': '5206607081334906820',
        'REFERRAL_WITHDRAWAL_REJECTED': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_COMPLETED': '5206607081334906820',
        'REFERRAL_WITHDRAWAL_CANCELLED': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_STATS_PENDING': '5386367538735104399',
        'REFERRAL_WITHDRAWAL_DETAILS_TOO_SHORT': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_INVALID_AMOUNT': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_MIN_ERROR': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_INSUFFICIENT': '5210952531676504517',
        'REFERRAL_WITHDRAWAL_ERROR_PREFIX': '5210952531676504517',
    }

    for locale in _locales().values():
        assert 'emoji-id="5409048419211682843"' in locale['REFERRAL_WITHDRAWAL_TITLE']
        assert 'emoji-id="5334544901428229844"' in locale['REFERRAL_WITHDRAWAL_ONLY_REF_MODE']
        assert 'emoji-id="5210952531676504517"' in locale['REFERRAL_WITHDRAWAL_MIN_AVAILABLE_ERROR']
        for key, emoji_id in expected.items():
            assert f'emoji-id="{emoji_id}"' in locale[key], key


def test_referral_withdrawal_copy_renders_dynamic_values():
    samples = {
        'REFERRAL_WITHDRAWAL_STATS_EARNED': {'amount': '100 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_SPENT': {'amount': '20 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_WITHDRAWN': {'amount': '30 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_AVAILABLE': {'amount': '50 ₽'},
        'REFERRAL_WITHDRAWAL_MIN_AMOUNT': {'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_COOLDOWN': {'days': 5},
        'REFERRAL_WITHDRAWAL_MIN_AVAILABLE_ERROR': {'minimum': '500 ₽', 'available': '50 ₽'},
        'REFERRAL_WITHDRAWAL_ENTER_AMOUNT': {'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_CONFIRM_DETAILS': {'details': '+7 999 123-45-67'},
        'REFERRAL_WITHDRAWAL_SUCCESS': {'id': 7, 'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_APPROVED': {'id': 7, 'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_REJECTED': {'id': 7, 'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_COMPLETED': {'id': 7, 'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_STATS_PENDING': {'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_MIN_ERROR': {'amount': '500 ₽'},
        'REFERRAL_WITHDRAWAL_INSUFFICIENT': {'amount': '50 ₽'},
    }

    for locale in _locales().values():
        for key, values in samples.items():
            rendered = locale[key].format(**values)
            assert '{' not in rendered
            assert '}' not in rendered
