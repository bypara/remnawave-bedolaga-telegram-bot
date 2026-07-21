from app.localization.texts import get_texts


def test_support_title_uses_requested_custom_emoji_in_both_languages():
    for language in ('ru', 'en'):
        support_info = get_texts(language).SUPPORT_INFO

        assert 'emoji-id="5258337316715373336"' in support_info
        assert '🛟' not in support_info


def test_support_topup_copy_uses_requested_custom_emojis_and_methods():
    for language in ('ru', 'en'):
        support_topup = get_texts(language).SUPPORT_TOPUP_INFO

        assert 'emoji-id="5341715473882955310"' in support_topup
        assert 'emoji-id="5334544901428229844"' in support_topup
        assert '{contact}' in support_topup
        assert '{user_id}' in support_topup
        assert 'Другие платежные системы' not in support_topup
