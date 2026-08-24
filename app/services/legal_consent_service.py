"""Обязательное согласие с офертой и политикой в кабинете.

В боте согласие с правилами спрашивается при регистрации, но живёт только в FSM и
никуда не сохраняется. В кабинете новый пользователь создавался вообще молча: зашёл
через Telegram — аккаунт готов, никаких документов ему не показывали.

Здесь один источник правды на весь кабинет: какие документы требуют галочки, нужна
ли она вообще, как записать факт согласия и разрешено ли платное действие. Ключевое правило — требовать согласие
можно только с тем, что пользователь способен прочитать: если документ выключен или
скрыт из веба, галочки по нему нет. Иначе установка без заполненной оферты
заблокировала бы регистрацию вообще всем.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import LegalConsent, User
from app.services.privacy_policy_service import PrivacyPolicyService
from app.services.public_offer_service import PublicOfferService
from app.utils.display_mode import is_visible_in_web


logger = structlog.get_logger(__name__)

PUBLIC_OFFER = 'public_offer'
PRIVACY_POLICY = 'privacy_policy'

# Порядок важен: в таком виде чекбоксы показываются пользователю.
KNOWN_DOCUMENTS: tuple[str, ...] = (PUBLIC_OFFER, PRIVACY_POLICY)


@dataclass(slots=True)
class LegalConsentRequirement:
    """Что кабинет должен показать на обязательном экране согласия."""

    required: bool
    prechecked: bool
    documents: list[str]


@dataclass(slots=True)
class UserLegalConsentStatus:
    """Текущее состояние обязательных документов для конкретного пользователя."""

    required: bool
    prechecked: bool
    documents: list[str]
    accepted_documents: list[str]
    missing_documents: list[str]

    @property
    def has_accepted_all(self) -> bool:
        return not self.missing_documents


async def _document_is_available(db: AsyncSession, document: str, language: str) -> bool:
    """Есть ли документ, который пользователь реально сможет открыть."""
    if document == PUBLIC_OFFER:
        if not is_visible_in_web(settings.PUBLIC_OFFER_DISPLAY_MODE):
            return False
        offer = await PublicOfferService.get_offer(db, PublicOfferService.normalize_language(language), fallback=True)
        return bool(offer and (offer.content or '').strip())

    if document == PRIVACY_POLICY:
        if not is_visible_in_web(settings.PRIVACY_POLICY_DISPLAY_MODE):
            return False
        policy = await PrivacyPolicyService.get_policy(
            db, PrivacyPolicyService.normalize_language(language), fallback=True
        )
        return bool(policy and (policy.content or '').strip())

    return False


async def get_requirement(db: AsyncSession, language: str = 'ru') -> LegalConsentRequirement:
    """Текущий набор документов, обязательный для пользователей кабинета."""
    if not settings.CABINET_REQUIRE_LEGAL_CONSENT:
        return LegalConsentRequirement(required=False, prechecked=False, documents=[])

    documents: list[str] = []
    for document in KNOWN_DOCUMENTS:
        try:
            if await _document_is_available(db, document, language):
                documents.append(document)
        except Exception as error:  # pragma: no cover - defensive
            # Сбой чтения документа не должен закрывать вход в кабинет: без документа
            # галочки по нему просто не будет.
            logger.warning('Не удалось проверить доступность документа', document=document, error=str(error))

    return LegalConsentRequirement(
        required=bool(documents),
        prechecked=bool(settings.CABINET_LEGAL_CONSENT_PRECHECKED),
        documents=documents,
    )


def missing_documents(required: list[str], accepted: list[str] | None) -> list[str]:
    """Какие из обязательных документов пользователь не отметил."""
    accepted_set = {item.strip() for item in (accepted or []) if isinstance(item, str)}
    return [document for document in required if document not in accepted_set]


async def get_accepted_documents(
    db: AsyncSession,
    user_id: int,
    documents: list[str] | None = None,
) -> set[str]:
    """Какие документы пользователь уже принимал хотя бы один раз."""
    query = select(LegalConsent.document).where(LegalConsent.user_id == user_id)
    if documents:
        query = query.where(LegalConsent.document.in_(documents))
    result = await db.execute(query)
    return set(result.scalars().all())


async def get_user_status(
    db: AsyncSession,
    user: User,
    language: str = 'ru',
) -> UserLegalConsentStatus:
    """Вернуть обязательные, принятые и недостающие документы пользователя."""
    requirement = await get_requirement(db, language)
    accepted_set = await get_accepted_documents(db, user.id, requirement.documents)
    accepted = [document for document in requirement.documents if document in accepted_set]
    missing = [document for document in requirement.documents if document not in accepted_set]
    return UserLegalConsentStatus(
        required=requirement.required,
        prechecked=requirement.prechecked,
        documents=requirement.documents,
        accepted_documents=accepted,
        missing_documents=missing,
    )


def _consent_required_error(state: UserLegalConsentStatus) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        detail={
            'code': 'legal_consent_required',
            'message': 'Accept the public offer and privacy policy to continue',
            'documents': state.documents,
            'missing': state.missing_documents,
            'prechecked': state.prechecked,
        },
    )


async def require_user_consent(
    db: AsyncSession,
    user: User,
    language: str | None = None,
) -> UserLegalConsentStatus:
    """Серверный гейт платных действий и триала — UI обойти нельзя."""
    state = await get_user_status(db, user, language or getattr(user, 'language', None) or 'ru')
    if state.required and not state.has_accepted_all:
        raise _consent_required_error(state)
    return state


async def accept_user_consent(
    db: AsyncSession,
    user: User,
    accepted: list[str] | None,
    *,
    language: str | None = None,
    source: str = 'cabinet_onboarding',
    ip_address: str | None = None,
) -> UserLegalConsentStatus:
    """Зафиксировать явное согласие со всеми актуальными документами.

    Частичное принятие не сохраняется: пользователь либо принимает весь доступный
    комплект, либо остаётся на обязательном экране.
    """
    state = await get_user_status(db, user, language or getattr(user, 'language', None) or 'ru')
    missing_from_request = missing_documents(state.documents, accepted)
    if state.required and missing_from_request:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                'code': 'legal_consent_required',
                'message': 'All required documents must be accepted',
                'documents': state.documents,
                'missing': missing_from_request,
                'prechecked': state.prechecked,
            },
        )

    to_record = [document for document in state.documents if document not in state.accepted_documents]
    if to_record:
        try:
            for document in to_record:
                db.add(
                    LegalConsent(
                        user_id=user.id,
                        document=document,
                        source=source,
                        ip_address=ip_address,
                    )
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return await get_user_status(db, user, language or getattr(user, 'language', None) or 'ru')


async def record_consent(
    db: AsyncSession,
    user: User,
    documents: list[str],
    *,
    source: str,
    ip_address: str | None = None,
    commit: bool = True,
) -> None:
    """Записать факт согласия. Сбой записи не должен ронять регистрацию."""
    if not documents:
        return

    try:
        for document in documents:
            db.add(LegalConsent(user_id=user.id, document=document, source=source, ip_address=ip_address))
        if commit:
            await db.commit()
    except Exception as error:  # pragma: no cover - defensive
        logger.error('Не удалось записать согласие с документами', user_id=user.id, error=str(error))
        if commit:
            await db.rollback()
