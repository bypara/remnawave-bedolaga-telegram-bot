"""Helpers for URL-based legal documents shown by the Telegram bot."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.legal_consent_service import record_consent
from app.services.privacy_policy_service import PrivacyPolicyService
from app.services.public_offer_service import PublicOfferService


PRIVACY_POLICY = 'privacy_policy'
PUBLIC_OFFER = 'public_offer'


def normalize_legal_document_url(value: str | None) -> str | None:
    """Return a safe HTTP(S) URL or ``None`` for legacy text/invalid input."""
    candidate = (value or '').strip()
    if not candidate or any(character.isspace() for character in candidate):
        return None

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None

    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        return None
    return candidate


_HTML_LINK_RE = re.compile(r"""href\s*=\s*["'](https?://[^"']+)["']""", re.IGNORECASE)
_PLAIN_LINK_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)


def extract_legal_document_url(value: str | None) -> str | None:
    """Read a URL from legacy document text without allowing prose in new admin input."""
    direct_url = normalize_legal_document_url(value)
    if direct_url:
        return direct_url

    content = value or ''
    html_match = _HTML_LINK_RE.search(content)
    if html_match:
        return normalize_legal_document_url(html_match.group(1))

    plain_match = _PLAIN_LINK_RE.search(content)
    if not plain_match:
        return None
    return normalize_legal_document_url(plain_match.group(0).rstrip('.,);]'))


@dataclass(frozen=True, slots=True)
class LegalDocumentLinks:
    privacy_policy: str | None = None
    public_offer: str | None = None

    @property
    def documents(self) -> list[str]:
        result: list[str] = []
        if self.privacy_policy:
            result.append(PRIVACY_POLICY)
        if self.public_offer:
            result.append(PUBLIC_OFFER)
        return result


async def get_active_legal_document_links(db: AsyncSession, language: str) -> LegalDocumentLinks:
    """Load enabled localized document links, including the configured language fallback."""
    policy = await PrivacyPolicyService.get_active_policy(db, language)
    offer = await PublicOfferService.get_active_offer(db, language)
    return LegalDocumentLinks(
        privacy_policy=extract_legal_document_url(policy.content if policy else None),
        public_offer=extract_legal_document_url(offer.content if offer else None),
    )


def format_implicit_consent_notice(texts, links: LegalDocumentLinks, *, action: str) -> str:
    """Build the localized notice displayed directly before a legal action."""
    documents: list[str] = []
    if links.privacy_policy:
        label = texts.t('LEGAL_PRIVACY_POLICY_LINK_LABEL', 'политикой конфиденциальности')
        documents.append(f'<a href="{html.escape(links.privacy_policy, quote=True)}">{html.escape(label)}</a>')
    if links.public_offer:
        label = texts.t('LEGAL_PUBLIC_OFFER_LINK_LABEL', 'публичной офертой')
        documents.append(f'<a href="{html.escape(links.public_offer, quote=True)}">{html.escape(label)}</a>')

    if not documents:
        return ''

    if len(documents) == 1:
        documents_text = documents[0]
    else:
        conjunction = texts.t('LEGAL_DOCUMENTS_CONJUNCTION', 'и')
        documents_text = f'{documents[0]} {html.escape(conjunction)} {documents[1]}'

    return texts.t(
        'LEGAL_IMPLICIT_CONSENT_NOTICE',
        'Нажимая {action}, вы соглашаетесь с {documents}.',
    ).format(action=html.escape(action), documents=documents_text)


async def build_implicit_consent_notice(
    db: AsyncSession,
    texts,
    *,
    action_key: str,
    action_fallback: str,
) -> str:
    links = await get_active_legal_document_links(db, texts.language)
    action = texts.t(action_key, action_fallback)
    return format_implicit_consent_notice(texts, links, action=action)


async def record_implicit_legal_consent(
    db: AsyncSession,
    user,
    *,
    language: str,
    source: str,
) -> None:
    """Persist which enabled URL documents were accepted by clicking an action."""
    links = await get_active_legal_document_links(db, language)
    await record_consent(db, user, links.documents, source=source)
