"""Build manual activation links and send email codes over authenticated TLS SMTP."""

import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings
from app.errors import HubError


def require_mailer() -> None:
    if not get_settings().smtp_configured:
        raise HubError("EMAIL_UNAVAILABLE", "Email delivery is not configured yet", 503)


def send_email(recipient: str, subject: str, body: str) -> None:
    require_mailer()
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        context = ssl.create_default_context()
        if settings.smtp_tls_mode == "ssl":
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HubError("EMAIL_UNAVAILABLE", "Email could not be delivered. Try again later.", 503) from exc


def activation_url(token: str) -> str:
    settings = get_settings()
    base = (settings.admin_console_url or settings.mcp_issuer_url).rstrip("/")
    if settings.environment == "production" and not base.startswith("https://"):
        raise HubError("EMAIL_UNAVAILABLE", "Admin console URL must use HTTPS", 503)
    # A fragment stays out of HTTP requests and server access logs.
    return f"{base}/activate#{token}"


def send_activation_code(recipient: str, code: str) -> None:
    send_email(recipient, "Verify your MCP Hub email", f"Your MCP Hub activation code is {code}.\n\n"
               "It expires in 10 minutes and works once. If you did not request it, ignore this email.\n")
