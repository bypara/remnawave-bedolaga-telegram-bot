"""Dependency-free validation shared by environment and live admin settings."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit


def validate_migration_value(key: str, value: object) -> object:
    if key == 'BOT_MIGRATION_BONUS_AMOUNT_RUBLES':
        try:
            amount = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError('Введите сумму бонуса в рублях.') from error
        if (
            not amount.is_finite()
            or amount < 0
            or amount > 100000
            or amount * 100 != (amount * 100).to_integral_value()
        ):
            raise ValueError('Сумма бонуса: от 0 до 100000 ₽, не более двух знаков после запятой.')
        return float(amount)
    if key == 'BOT_MIGRATION_URL':
        url = str(value or '').strip()
        if not url:
            return ''
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != 'https'
            or parsed.netloc != 't.me'
            or not re.fullmatch(r'/[A-Za-z][A-Za-z0-9_]{4,31}', parsed.path)
            or parsed.fragment
            or any(character.isspace() for character in url)
            or (parsed.query and (set(query) != {'start'} or len(query['start']) != 1))
            or ('start' in query and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', query['start'][0]))
        ):
            raise ValueError('Укажите https://t.me/имя_бота или такую же ссылку с ?start=код (до 64 символов).')
        return url
    if key in {
        'BOT_MIGRATION_MESSAGE',
        'BOT_MIGRATION_BUTTON_TEXT',
        'BOT_MIGRATION_BONUS_SUCCESS_MESSAGE',
        'BOT_MIGRATION_NO_BONUS_MESSAGE',
        'BOT_MIGRATION_NO_BONUS_BUTTON_TEXT',
    }:
        text = str(value or '').strip()
        limit = 64 if key.endswith('BUTTON_TEXT') else 3500
        # Telegram counts UTF-16 units; leave room below its message limit.
        if not text or len(text.replace('{bonus}', '99999.99').encode('utf-16-le')) // 2 > limit:
            raise ValueError(f'Введите непустой текст длиной до {limit} символов.')
        return text
    return value


def migration_bonus_kopeks(amount_rubles: object) -> int:
    amount = validate_migration_value('BOT_MIGRATION_BONUS_AMOUNT_RUBLES', amount_rubles)
    return int(Decimal(str(amount)) * 100)


def render_migration_text(text: str, amount_kopeks: int) -> str:
    amount = format(Decimal(amount_kopeks) / 100, '.2f').rstrip('0').rstrip('.')
    return text.replace('{bonus}', amount)
