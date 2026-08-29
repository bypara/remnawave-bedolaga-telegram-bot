"""Email delivery for authentication, notifications and broadcasts."""

import base64
import re
import smtplib
import time
import uuid
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

import httpx
import structlog

from app.config import settings


logger = structlog.get_logger(__name__)


class EmailService:
    """Send rendered messages through SMTP or the Resend HTTPS API."""

    @property
    def provider(self) -> str:
        return settings.get_email_provider()

    @property
    def host(self) -> str | None:
        return settings.SMTP_HOST

    @property
    def port(self) -> int:
        return settings.SMTP_PORT

    @property
    def user(self) -> str | None:
        return settings.SMTP_USER

    @property
    def password(self) -> str | None:
        return settings.SMTP_PASSWORD

    @property
    def from_email(self) -> str | None:
        return settings.get_smtp_from_email()

    @property
    def from_name(self) -> str:
        return settings.SMTP_FROM_NAME

    @property
    def reply_to(self) -> str:
        return (settings.SMTP_REPLY_TO or '').strip()

    @property
    def use_tls(self) -> bool:
        return settings.SMTP_USE_TLS

    @property
    def use_ssl(self) -> bool:
        # Port 465 always implies implicit TLS (SMTPS, RFC 8314).
        return settings.SMTP_USE_SSL or self.port == 465

    def is_configured(self) -> bool:
        """Check whether the selected email transport is configured."""
        return settings.is_email_delivery_configured()

    @staticmethod
    def _html_to_plain_text(body_html: str) -> str:
        """Грубая конвертация HTML в text/plain для multipart/alternative.

        Блоки <style>/<script> удаляются ЦЕЛИКОМ до вырезания тегов: сами теги
        регулярка убирала и раньше, а их содержимое (CSS/JS-правила) утекало в
        текстовую версию письма перед основным текстом (#2974).

        &amp; расшифровывается ПОСЛЕДНИМ: иначе "&amp;lt;" проходит двойную
        расшифровку и превращается в "<" вместо "&lt;".
        """
        text = re.sub(r'<(style|script)\b[^>]*>.*?</\1\s*>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
        # Запасной проход для битого шаблона (кастомные письма из админки): открытый
        # <style>/<script> без закрывающего тега иначе утёк бы телом CSS/JS в текст —
        # срезаем висячий блок до конца ввода.
        text = re.sub(r'<(style|script)\b[^>]*>.*', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        # После удаления блоков и тегов остаются простыни пустых строк —
        # схлопываем, чтобы текст не начинался с десятков переносов.
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()

    def _get_smtp_connection(self) -> smtplib.SMTP:
        """Create and return SMTP connection."""
        if self.use_ssl:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
            smtp.ehlo()
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=30)
            smtp.ehlo()
            if self.use_tls:
                smtp.starttls()
                smtp.ehlo()

        # Only attempt login if credentials are provided AND server supports AUTH
        if self.user and self.password:
            if smtp.has_extn('auth'):
                smtp.login(self.user, self.password)
            else:
                logger.debug('SMTP server does not support AUTH, skipping authentication', host=self.host)

        return smtp

    def _get_unsubscribe_headers(self, unsubscribe_url: str | None) -> dict[str, str]:
        """Build safe RFC 8058 headers shared by both delivery transports."""
        if not unsubscribe_url:
            return {}

        safe_unsubscribe = unsubscribe_url.strip()
        if any(ch in safe_unsubscribe for ch in '\r\n<>') or not safe_unsubscribe.startswith(('http://', 'https://')):
            logger.warning('Некорректный unsubscribe_url — заголовки отписки пропущены')
            return {}

        from .email_unsubscribe import build_unsubscribe_mailto

        targets = [f'<{safe_unsubscribe}>']
        if mailto := build_unsubscribe_mailto():
            targets.append(f'<{mailto}>')
        return {
            'List-Unsubscribe': ', '.join(targets),
            'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
        }

    def _get_safe_reply_to(self) -> str:
        reply_to = self.reply_to
        if not reply_to:
            return ''
        if any(ch in reply_to for ch in '\r\n') or '@' not in reply_to:
            logger.warning('Некорректный SMTP_REPLY_TO — заголовок Reply-To пропущен')
            return ''
        return reply_to

    def _send_via_smtp(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
        sender_email: str,
        sender_name: str,
        attachments: list[tuple[str, bytes, str]] | None,
        extra_headers: dict[str, str],
    ) -> bool:
        """Send one message using the legacy SMTP transport."""
        try:
            alternative = MIMEMultipart('alternative')
            msg = MIMEMultipart('mixed') if attachments else alternative
            msg['Subject'] = subject
            msg['From'] = formataddr((sender_name, sender_email))
            msg['To'] = to_email
            if reply_to := self._get_safe_reply_to():
                msg['Reply-To'] = formataddr((sender_name, reply_to))
            msg['Date'] = formatdate(localtime=False)
            msg['Message-ID'] = make_msgid(domain=sender_email.rsplit('@', maxsplit=1)[-1])
            for header_name, header_value in extra_headers.items():
                msg[header_name] = header_value

            alternative.attach(MIMEText(body_text, 'plain', 'utf-8'))
            alternative.attach(MIMEText(body_html, 'html', 'utf-8'))

            if attachments:
                msg.attach(alternative)
                for filename, content, mimetype in attachments:
                    maintype, _, subtype = (mimetype or 'application/octet-stream').partition('/')
                    attachment_part = MIMEBase(maintype or 'application', subtype or 'octet-stream')
                    attachment_part.set_payload(content)
                    encoders.encode_base64(attachment_part)
                    safe_filename = filename.replace('\n', '').replace('\r', '')
                    attachment_part.add_header('Content-Disposition', 'attachment', filename=safe_filename)
                    msg.attach(attachment_part)

            with self._get_smtp_connection() as smtp:
                smtp.sendmail(sender_email, to_email, msg.as_string())

            logger.info('Email sent successfully', provider='smtp', to_email=to_email)
            return True
        except Exception as error:
            logger.error('Failed to send email', provider='smtp', to_email=to_email, error=error)
            return False

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        """Return a short bounded retry delay, respecting numeric Retry-After."""
        if response is not None:
            try:
                return min(10.0, max(0.0, float(response.headers.get('Retry-After', ''))))
            except (TypeError, ValueError):
                pass
        base = max(0.0, float(settings.EMAIL_SEND_RETRY_BASE_SECONDS))
        return min(10.0, base * (2 ** max(0, attempt - 1)))

    def _send_via_resend(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
        sender_email: str,
        sender_name: str,
        attachments: list[tuple[str, bytes, str]] | None,
        extra_headers: dict[str, str],
    ) -> bool:
        """Send one message using Resend's HTTPS API with bounded retries."""
        payload: dict[str, Any] = {
            'from': formataddr((sender_name, sender_email)),
            'to': [to_email],
            'subject': subject,
            'html': body_html,
            'text': body_text,
        }
        if reply_to := self._get_safe_reply_to():
            payload['reply_to'] = reply_to
        if extra_headers:
            payload['headers'] = extra_headers
        if attachments:
            payload['attachments'] = [
                {
                    'filename': filename.replace('\n', '').replace('\r', ''),
                    'content': base64.b64encode(content).decode('ascii'),
                    'content_type': mimetype or 'application/octet-stream',
                }
                for filename, content, mimetype in attachments
            ]

        headers = {
            'Authorization': f'Bearer {settings.RESEND_API_KEY.strip()}',
            'Content-Type': 'application/json',
            # Reuse this value for every retry: if Resend accepted the first
            # request but our connection died before the response, it will not
            # create a duplicate email.
            'Idempotency-Key': str(uuid.uuid4()),
        }
        max_attempts = max(1, min(5, int(settings.EMAIL_SEND_MAX_ATTEMPTS)))

        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            for attempt in range(1, max_attempts + 1):
                response: httpx.Response | None = None
                try:
                    response = client.post(settings.RESEND_API_URL, headers=headers, json=payload)
                    if response.is_success:
                        try:
                            message_id = response.json().get('id')
                        except ValueError:
                            message_id = None
                        logger.info(
                            'Email accepted by provider',
                            provider='resend',
                            to_email=to_email,
                            message_id=message_id,
                            attempt=attempt,
                        )
                        return True

                    retryable = response.status_code in {408, 429} or response.status_code >= 500
                    error_message = ''
                    try:
                        error_message = str(response.json().get('message') or '')[:300]
                    except ValueError:
                        error_message = response.text[:300]
                    logger.warning(
                        'Email provider rejected request',
                        provider='resend',
                        to_email=to_email,
                        status_code=response.status_code,
                        error=error_message,
                        attempt=attempt,
                        retryable=retryable,
                    )
                    if not retryable:
                        return False
                except httpx.RequestError as error:
                    logger.warning(
                        'Email provider request failed',
                        provider='resend',
                        to_email=to_email,
                        error=type(error).__name__,
                        attempt=attempt,
                    )

                if attempt < max_attempts:
                    time.sleep(self._retry_delay(response, attempt))

        logger.error('Failed to send email after retries', provider='resend', to_email=to_email, attempts=max_attempts)
        return False

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        unsubscribe_url: str | None = None,
    ) -> bool:
        """
        Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            body_html: HTML body content
            body_text: Plain text body (optional, generated from HTML if not provided)
            attachments: Optional list of (filename, content, mimetype) tuples
            unsubscribe_url: One-click unsubscribe URL. Задаётся ТОЛЬКО для
                маркетинговых писем — на транзакционных (код входа, чек об
                оплате) List-Unsubscribe не ставят.

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.warning('Email delivery provider is not configured', provider=self.provider)
            return False

        sender_email = self.from_email
        if not sender_email or '@' not in sender_email:
            logger.error('Invalid or missing SMTP from_email, cannot send email', from_email=sender_email)
            return False

        # Defensive: strip newlines to prevent header injection.
        to_email = to_email.strip().replace('\n', '').replace('\r', '')
        subject = subject.replace('\n', '').replace('\r', '')
        safe_from_name = self.from_name.replace('\n', '').replace('\r', '') if self.from_name else ''
        safe_from_email = sender_email.replace('\n', '').replace('\r', '')
        body_text = body_text if body_text is not None else self._html_to_plain_text(body_html)
        extra_headers = self._get_unsubscribe_headers(unsubscribe_url)

        kwargs = {
            'to_email': to_email,
            'subject': subject,
            'body_html': body_html,
            'body_text': body_text,
            'sender_email': safe_from_email,
            'sender_name': safe_from_name,
            'attachments': attachments,
            'extra_headers': extra_headers,
        }
        if self.provider == 'resend':
            return self._send_via_resend(**kwargs)
        if self.provider == 'smtp':
            return self._send_via_smtp(**kwargs)

        logger.error('Unknown email delivery provider', provider=self.provider)
        return False

    def _render_default_template(
        self,
        notification_type: str,
        language: str,
        context: dict[str, Any],
    ) -> tuple[str, str] | None:
        """
        Render the built-in default template for an auth email.

        Single source of truth: the same EmailNotificationTemplates the admin
        editor and the notification delivery service use — what the admin sees
        in the editor preview is exactly what this service sends.

        Imports are lazy to avoid a module cycle
        (notification_delivery_service imports this module).
        """
        from app.services.notification_delivery_service import NotificationType

        from .email_templates import EmailNotificationTemplates

        try:
            template = EmailNotificationTemplates().get_template(NotificationType(notification_type), language, context)
        except Exception as e:
            logger.error(
                'Не удалось отрендерить дефолтный email шаблон',
                notification_type=notification_type,
                language=language,
                error=e,
            )
            return None
        if not template:
            return None
        return (template['subject'], template['body_html'])

    def send_verification_email(
        self,
        to_email: str,
        verification_token: str,
        verification_url: str,
        username: str | None = None,
        language: str = 'ru',
        custom_subject: str | None = None,
        custom_body_html: str | None = None,
    ) -> bool:
        """
        Send email verification email.

        Args:
            to_email: Recipient email address
            verification_token: Verification token
            verification_url: Base URL for verification (token will be appended)
            username: User's name for personalization
            language: Language code (ru, en, zh, ua, fa)
            custom_subject: Override subject from admin template
            custom_body_html: Override body HTML from admin template (already wrapped in base template)

        Returns:
            True if email was sent successfully, False otherwise
        """
        if custom_subject and custom_body_html:
            return self.send_email(to_email, custom_subject, custom_body_html)

        rendered = self._render_default_template(
            'email_verification',
            language,
            {
                'username': username or '',
                'verification_url': f'{verification_url}?token={verification_token}',
                'expire_hours': settings.get_cabinet_email_verification_expire_hours(),
            },
        )
        if not rendered:
            return False
        return self.send_email(to_email, *rendered)

    def send_password_reset_email(
        self,
        to_email: str,
        reset_token: str,
        reset_url: str,
        username: str | None = None,
        language: str = 'ru',
        custom_subject: str | None = None,
        custom_body_html: str | None = None,
    ) -> bool:
        """
        Send password reset email.

        Args:
            to_email: Recipient email address
            reset_token: Password reset token
            reset_url: Base URL for password reset (token will be appended)
            username: User's name for personalization
            language: Language code (ru, en, zh, ua, fa)
            custom_subject: Override subject from admin template
            custom_body_html: Override body HTML from admin template (already wrapped in base template)

        Returns:
            True if email was sent successfully, False otherwise
        """
        if custom_subject and custom_body_html:
            return self.send_email(to_email, custom_subject, custom_body_html)

        rendered = self._render_default_template(
            'password_reset',
            language,
            {
                'username': username or '',
                'reset_url': f'{reset_url}?token={reset_token}',
                'expire_hours': settings.get_cabinet_password_reset_expire_hours(),
            },
        )
        if not rendered:
            return False
        return self.send_email(to_email, *rendered)

    def send_email_change_code(
        self,
        to_email: str,
        code: str,
        username: str | None = None,
        language: str = 'ru',
        custom_subject: str | None = None,
        custom_body_html: str | None = None,
    ) -> bool:
        """
        Send email change verification code.

        Args:
            to_email: New email address
            code: 6-digit verification code
            username: User's name for personalization
            language: Language code (ru, en, zh, ua, fa)
            custom_subject: Override subject from admin template
            custom_body_html: Override body HTML from admin template

        Returns:
            True if email was sent successfully, False otherwise
        """
        if custom_subject and custom_body_html:
            return self.send_email(to_email, custom_subject, custom_body_html)

        rendered = self._render_default_template(
            'email_change_code',
            language,
            {
                'username': username or '',
                'code': code,
                'expire_minutes': settings.get_cabinet_email_change_code_expire_minutes(),
            },
        )
        if not rendered:
            return False
        return self.send_email(to_email, *rendered)


# Singleton instance
email_service = EmailService()
