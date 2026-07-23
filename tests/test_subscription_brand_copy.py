import json
from pathlib import Path


BRAND_LOCALES_DIR = Path(__file__).resolve().parents[1] / 'app' / 'localization' / 'brand_locales'


def _locales():
    return {
        language: json.loads((BRAND_LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
        for language in ('ru', 'en')
    }


def test_subscription_copy_uses_requested_custom_emoji():
    locales = _locales()
    expected = {
        'SUBSCRIPTION_RENEWAL_MENU_TEXT': '5199457120428249992',
        'SUBSCRIPTION_RENEWAL_CONFIRM_TEXT': '5258501105293205250',
        'AUTOPAY_MENU_TEXT': '5258258882022612173',
        'SUBSCRIPTION_SETTINGS_OVERVIEW': '5258096772776991776',
        'DEVICE_MANAGEMENT_OVERVIEW': '5452165780579843515',
        'DEVICE_RESET_ALL_SUCCESS_MESSAGE': '5260341314095947411',
        'DEVICE_RENAME_PROMPT': '5258430848218176413',
        'SUBSCRIPTION_REVOKE_WARNING': '5240241223632954241',
        'SUBSCRIPTION_REVOKE_SUCCESS': '5206607081334906820',
        'ADD_TRAFFIC_PROMPT': '5274008024585871702',
        'SUBSCRIPTION_PURCHASED_TRAFFIC_TITLE': '5258134813302332906',
        'BALANCE_HISTORY_EMPTY': '5210952531676504517',
        'TARIFF_LIST_TITLE': '5258477770735885832',
        'TARIFF_INFO_TEXT': '5260730055880876557',
        'TARIFF_INFO_DESCRIPTION': '5257965174979042426',
        'SUBSCRIPTION_PURCHASE_CONFIRM_TEXT': '5258501105293205250',
        'SUBSCRIPTION_PURCHASE_SUCCESS_TEXT': '5461151367559141950',
        'SUBSCRIPTION_RENEWAL_SUCCESS_TEXT': '5461151367559141950',
        'TRIAL_AVAILABLE': '5447410659077661506',
        'TRIAL_ACTIVATED': '5461151367559141950',
        'SUBSCRIPTION_IMPORT_LINK_SECTION': '5260730055880876557',
        'SUBSCRIPTION_IMPORT_INSTRUCTION_PROMPT': '5258328383183396223',
        'SUBSCRIPTION_CONNECT_MINIAPP_MESSAGE': '5251203410396458957',
        'TARIFF_RENEW_CHOOSE_TARIFF': '5348125953090403204',
        'SUBSCRIPTION_INSUFFICIENT_FUNDS_TEXT': '5210952531676504517',
        'PAYMENT_METHODS_TITLE': '5258204546391351475',
        'PRIVACY_POLICY_HEADER': '5251203410396458957',
        'PUBLIC_OFFER_HEADER': '5282843764451195532',
    }

    for locale in locales.values():
        for key, emoji_id in expected.items():
            assert f'emoji-id="{emoji_id}"' in locale[key], key

        assert 'emoji-id="5271604874419647061"' in locale['SUBSCRIPTION_CONNECT_MINIAPP_MESSAGE']
        assert '<b>' in locale['PRIVACY_POLICY_HEADER']
        assert '<b>' in locale['PUBLIC_OFFER_HEADER']


def test_subscription_copy_renders_dynamic_values_in_both_languages():
    samples = {
        'SUBSCRIPTION_RENEWAL_MENU_TEXT': {
            'discount_hint': '',
            'tariff': 'Standard',
            'traffic': '0 / 100 GB',
            'devices': 1,
        },
        'SUBSCRIPTION_RENEWAL_CONFIRM_TEXT': {
            'tariff': 'Standard',
            'traffic': '0 / 100 GB',
            'period': '14 days',
            'discount_text': '',
            'price': '500 ₽',
            'balance': '8499 ₽',
            'balance_after': '7999 ₽',
        },
        'SUBSCRIPTION_PURCHASE_SUCCESS_TEXT': {'period': '14 days', 'price': '500 ₽'},
        'SUBSCRIPTION_RENEWAL_SUCCESS_TEXT': {'period': '14 days', 'price': '500 ₽'},
        'TRIAL_AVAILABLE': {
            'days': '3 days',
            'traffic': '100 GB',
            'devices': '1 device',
            'price_line': '',
        },
        'SUBSCRIPTION_IMPORT_LINK_SECTION': {'subscription_url': 'https://sub.example/test'},
        'SUBSCRIPTION_INSUFFICIENT_FUNDS_TEXT': {
            'missing': '500 ₽',
            'cost': '500 ₽',
            'balance': '0 ₽',
        },
        'DEVICE_MANAGEMENT_OVERVIEW': {'total': 1, 'page': 1, 'pages': 1},
        'DEVICE_RENAME_PROMPT': {'current': '—', 'max_len': 64},
    }

    for locale in _locales().values():
        for key, values in samples.items():
            rendered = locale[key].format(**values)
            assert '{' not in rendered
