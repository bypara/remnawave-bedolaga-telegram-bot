import inspect
import json
from pathlib import Path

from app.handlers import referral


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_referral_list_copy_uses_requested_custom_emoji_in_both_languages():
    expected = {
        'REFERRAL_LIST_HEADER': '5258486128742244085',
        'REFERRAL_LIST_ITEM_HEADER': '5316727448644103237',
        'REFERRAL_LIST_ITEM_TOPUPS': '5260221883940347555',
        'REFERRAL_LIST_ITEM_EARNED': '5359719332542718652',
        'REFERRAL_LIST_ITEM_REGISTERED': '5258105663359294787',
        'REFERRAL_LIST_ITEM_ACTIVITY': '5258419835922030550',
        'REFERRAL_LIST_ITEM_ACTIVITY_LONG_AGO': '5258419835922030550',
    }

    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        for key, emoji_id in expected.items():
            assert f'emoji-id="{emoji_id}"' in locale[key]


def test_referral_list_keeps_pagination_and_continuous_numbering():
    source = inspect.getsource(referral.show_detailed_referral_list)

    assert 'limit=10' in source
    assert "referral_list_page_{page - 1}" in source
    assert "referral_list_page_{page + 1}" in source
    assert 'first_item_index = (page - 1) * 10 + 1' in source
