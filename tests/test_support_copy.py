from app.localization.texts import get_texts


def test_support_title_uses_requested_custom_emoji_in_both_languages():
    for language in ('ru', 'en'):
        support_info = get_texts(language).SUPPORT_INFO

        assert 'emoji-id="5258337316715373336"' in support_info
        assert '🛟' not in support_info
