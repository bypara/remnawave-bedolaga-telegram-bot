from app.localization.texts import get_texts
from app.services.legal_document_link_service import (
    LegalDocumentLinks,
    extract_legal_document_url,
    format_implicit_consent_notice,
    normalize_legal_document_url,
)


def test_normalize_legal_document_url_accepts_only_http_urls():
    assert normalize_legal_document_url(' https://example.com/privacy ') == 'https://example.com/privacy'
    assert normalize_legal_document_url('http://example.com/offer') == 'http://example.com/offer'
    assert normalize_legal_document_url('javascript:alert(1)') is None
    assert normalize_legal_document_url('example.com/privacy') is None
    assert normalize_legal_document_url('https://example.com/privacy policy') is None


def test_extract_legal_document_url_supports_legacy_text():
    assert (
        extract_legal_document_url('Документ опубликован: https://example.com/privacy.')
        == 'https://example.com/privacy'
    )
    assert (
        extract_legal_document_url('<a href="https://example.com/offer">Оферта</a>')
        == 'https://example.com/offer'
    )


def test_implicit_consent_notice_contains_both_clickable_documents():
    notice = format_implicit_consent_notice(
        get_texts('ru'),
        LegalDocumentLinks(
            privacy_policy='https://example.com/privacy?from=bot&lang=ru',
            public_offer='https://example.com/offer',
        ),
        action='«Активировать»',
    )

    assert 'Нажимая «Активировать»' in notice
    assert '<a href="https://example.com/privacy?from=bot&amp;lang=ru">политикой конфиденциальности</a>' in notice
    assert '<a href="https://example.com/offer">публичной офертой</a>' in notice


def test_implicit_consent_notice_is_empty_without_configured_links():
    assert format_implicit_consent_notice(get_texts('en'), LegalDocumentLinks(), action='“Pay”') == ''
