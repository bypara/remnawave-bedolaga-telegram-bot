import json
from pathlib import Path


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_add_traffic_success_copy_uses_requested_emoji_and_price():
    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        value = locale['ADD_TRAFFIC_SUCCESS']

        assert 'emoji-id="5206607081334906820"' in value
        assert 'emoji-id="5258204546391351475"' in value
        assert '{price}' in value
        assert '{traffic_gb}' not in value
        assert '{new_limit}' not in value
