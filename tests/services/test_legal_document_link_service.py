from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.localization.texts import get_texts
from app.services import legal_document_link_service as legal_links
from app.services.legal_document_link_service import (
    LegalDocumentLinks,
    extract_legal_document_url,
    format_browsing_consent_warning,
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


def test_browsing_consent_warning_contains_document_links():
    warning = format_browsing_consent_warning(
        get_texts('ru'),
        LegalDocumentLinks(
            privacy_policy='https://example.com/privacy',
            public_offer='https://example.com/offer',
        ),
    )

    assert 'Продолжая пользоваться ботом' in warning
    assert '<a href="https://example.com/privacy">политикой конфиденциальности</a>' in warning
    assert '<a href="https://example.com/offer">публичной офертой</a>' in warning


@pytest.mark.asyncio
async def test_bot_notice_is_hidden_when_documents_were_accepted_in_cabinet(monkeypatch):
    links = LegalDocumentLinks(
        privacy_policy='https://example.com/privacy',
        public_offer='https://example.com/offer',
    )
    monkeypatch.setattr(legal_links, 'get_active_legal_document_links', AsyncMock(return_value=links))
    monkeypatch.setattr(
        legal_links,
        'get_accepted_documents',
        AsyncMock(return_value={'privacy_policy', 'public_offer'}),
    )

    notice = await legal_links.build_implicit_consent_notice(
        AsyncMock(),
        get_texts('ru'),
        action_key='LEGAL_ACTION_ACTIVATE_TRIAL',
        action_fallback='«Активировать»',
        user=SimpleNamespace(id=7),
    )

    assert notice == ''


@pytest.mark.asyncio
async def test_bot_records_only_documents_missing_from_shared_consent(monkeypatch):
    links = LegalDocumentLinks(
        privacy_policy='https://example.com/privacy',
        public_offer='https://example.com/offer',
    )
    record_consent = AsyncMock()
    monkeypatch.setattr(legal_links, 'get_active_legal_document_links', AsyncMock(return_value=links))
    monkeypatch.setattr(
        legal_links,
        'get_accepted_documents',
        AsyncMock(return_value={'privacy_policy'}),
    )
    monkeypatch.setattr(legal_links, 'record_consent', record_consent)
    db = AsyncMock()
    user = SimpleNamespace(id=7)

    await legal_links.record_implicit_legal_consent(
        db,
        user,
        language='ru',
        source='bot_explore',
    )

    record_consent.assert_awaited_once_with(db, user, ['public_offer'], source='bot_explore')
