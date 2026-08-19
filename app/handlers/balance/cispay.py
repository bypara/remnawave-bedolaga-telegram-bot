"""Handler for cisPay balance top-up (api.cispay.app)."""

import structlog
from aiogram import types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import User
from app.keyboards.inline import get_back_keyboard
from app.keyboards.topup_amounts import get_topup_amount_keyboard, get_topup_amount_limits
from app.services.payment_service import PaymentService
from app.states import BalanceStates
from app.utils.decorators import error_handler

from .payment_ui import (
    build_amount_error,
    build_payment_create_error,
    build_payment_created_text,
    build_payment_keyboard,
    build_payment_processing_text,
    build_topup_prompt,
    build_topup_restriction_keyboard,
    build_topup_restriction_text,
)


logger = structlog.get_logger(__name__)


CISPAY_PAYMENT_METHODS = {'cispay', 'cispay_card', 'cispay_sbp'}

CISPAY_SERVICE_MAP: dict[str, str | None] = {
    'cispay': None,
    'cispay_card': 'card',
    'cispay_sbp': 'sbp',
}


def _extract_service_type(payment_method: str) -> str | None:
    return CISPAY_SERVICE_MAP.get(payment_method)


def _display_name_for_method(payment_method: str) -> str:
    if payment_method == 'cispay_sbp':
        return settings.get_cispay_sbp_display_name()
    if payment_method == 'cispay_card':
        return settings.get_cispay_card_display_name()
    return settings.get_cispay_display_name()


async def _create_cispay_payment_and_respond(
    message_or_callback,
    db_user: User,
    db: AsyncSession,
    amount_kopeks: int,
    edit_message: bool = False,
    payment_method_type: str | None = None,
):
    """Создаёт платёж cisPay и отправляет ссылку на страницу оплаты пользователю."""
    amount_rub = amount_kopeks / 100

    payment_service = PaymentService()
    description = settings.PAYMENT_BALANCE_TEMPLATE.format(
        service_name=settings.PAYMENT_SERVICE_NAME,
        description='Пополнение баланса',
    )

    result = await payment_service.create_cispay_payment(
        db=db,
        user_id=db_user.id,
        amount_kopeks=amount_kopeks,
        description=description,
        email=getattr(db_user, 'email', None),
        language=db_user.language,
        payment_method_type=payment_method_type,
    )

    if not result:
        error_text = build_payment_create_error(db_user.language)
        if edit_message:
            await message_or_callback.edit_text(
                error_text,
                reply_markup=get_back_keyboard(db_user.language),
                parse_mode='HTML',
            )
        else:
            await message_or_callback.answer(
                error_text,
                reply_markup=get_back_keyboard(db_user.language),
                parse_mode='HTML',
            )
        return

    payment_url = result.get('payment_url')
    display_name = _display_name_for_method(
        f'cispay_{payment_method_type}' if payment_method_type else 'cispay'
    )
    keyboard = build_payment_keyboard(db_user.language, payment_url, amount_kopeks)

    if payment_url:
        response_text = build_payment_created_text(db_user.language, display_name, amount_kopeks)
    else:
        response_text = build_payment_processing_text(db_user.language, display_name, amount_kopeks)

    if edit_message:
        await message_or_callback.edit_text(response_text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await message_or_callback.answer(response_text, reply_markup=keyboard, parse_mode='HTML')

    logger.info('cisPay payment created', telegram_id=db_user.telegram_id, amount_rub=amount_rub)


@error_handler
async def process_cispay_payment_amount(
    message: types.Message,
    db_user: User,
    db: AsyncSession,
    amount_kopeks: int,
    state: FSMContext,
):
    """Обрабатывает сумму, введённую пользователем для cisPay."""
    if getattr(db_user, 'restriction_topup', False):
        await message.answer(
            build_topup_restriction_text(db_user.language, getattr(db_user, 'restriction_reason', None)),
            parse_mode='HTML',
            reply_markup=build_topup_restriction_keyboard(db_user.language),
        )
        await state.clear()
        return

    data = await state.get_data()
    payment_method = data.get('payment_method', 'cispay')
    min_amount, max_amount = await get_topup_amount_limits(payment_method, db)

    if amount_kopeks < min_amount:
        await message.answer(
            build_amount_error(db_user.language, min_amount, minimum=True),
            reply_markup=get_back_keyboard(db_user.language),
            parse_mode='HTML',
        )
        return

    if amount_kopeks > max_amount:
        await message.answer(
            build_amount_error(db_user.language, max_amount, minimum=False),
            reply_markup=get_back_keyboard(db_user.language),
            parse_mode='HTML',
        )
        return

    payment_method_type = _extract_service_type(payment_method)

    await state.clear()

    await _create_cispay_payment_and_respond(
        message_or_callback=message,
        db_user=db_user,
        db=db,
        amount_kopeks=amount_kopeks,
        edit_message=False,
        payment_method_type=payment_method_type,
    )


async def _start_cispay_topup_impl(
    callback: types.CallbackQuery,
    db_user: User,
    state: FSMContext,
    payment_method: str,
):
    """Стартует FSM ввода суммы для cisPay."""
    if getattr(db_user, 'restriction_topup', False):
        await callback.message.edit_text(
            build_topup_restriction_text(db_user.language, getattr(db_user, 'restriction_reason', None)),
            parse_mode='HTML',
            reply_markup=build_topup_restriction_keyboard(db_user.language),
        )
        return

    await state.set_state(BalanceStates.waiting_for_amount)
    await state.update_data(payment_method=payment_method)

    min_amount_kopeks, max_amount_kopeks = await get_topup_amount_limits(payment_method)

    display_name = _display_name_for_method(payment_method)

    keyboard = await get_topup_amount_keyboard(payment_method, db_user.language)

    await callback.message.edit_text(
        build_topup_prompt(
            db_user.language,
            display_name,
            min_amount_kopeks,
            max_amount_kopeks,
        ),
        parse_mode='HTML',
        reply_markup=keyboard,
    )


@error_handler
async def start_cispay_topup(
    callback: types.CallbackQuery,
    db_user: User,
    db: AsyncSession,
    state: FSMContext,
):
    await _start_cispay_topup_impl(callback, db_user, state, 'cispay')


@error_handler
async def start_cispay_card_topup(
    callback: types.CallbackQuery,
    db_user: User,
    db: AsyncSession,
    state: FSMContext,
):
    await _start_cispay_topup_impl(callback, db_user, state, 'cispay_card')


@error_handler
async def start_cispay_sbp_topup(
    callback: types.CallbackQuery,
    db_user: User,
    db: AsyncSession,
    state: FSMContext,
):
    await _start_cispay_topup_impl(callback, db_user, state, 'cispay_sbp')
