"""Email alert service for low-star reviews."""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger("review_system.email_alert")


def send_low_rating_alert(
    reviewer_name: str,
    rating: int,
    review_text: str,
    suggested_reply: str,
    restaurant_name: str,
    location: str,
    review_id: int,
) -> bool:
    if not settings.smtp_user or not settings.alert_email_to:
        logger.warning("SMTP not configured, skipping email alert")
        return False

    subject = f"[{rating} Star] Negative Review Alert - {restaurant_name}"
    body = (
        f"A negative review requires your attention.\n\n"
        f"Restaurant: {restaurant_name}\n"
        f"Location: {location}\n"
        f"Reviewer: {reviewer_name}\n"
        f"Rating: {'*' * rating} ({rating}/5)\n"
        f"Review:\n{review_text}\n\n"
        f"--- AI Suggested Reply ---\n{suggested_reply}\n\n"
        f"Dashboard: http://localhost:8000/reviews/{review_id}\n\n"
        f"Please review and approve or edit the reply on the dashboard."
    )

    msg = MIMEMultipart()
    msg["From"] = settings.alert_email_from
    msg["To"] = settings.alert_email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info(f"Alert email sent for review {review_id} to {settings.alert_email_to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False


def send_daily_negative_review_report(report_title: str, report_body: str, recipients: list[str]) -> bool:
    clean_recipients = [item.strip() for item in recipients if item and item.strip()]
    if not settings.smtp_user or not clean_recipients:
        logger.warning("SMTP or report recipients not configured, skipping GM report email")
        return False

    msg = MIMEMultipart()
    msg["From"] = settings.alert_email_from
    msg["To"] = ", ".join(clean_recipients)
    msg["Subject"] = report_title
    msg.attach(MIMEText(report_body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("Daily negative review report sent to %s", clean_recipients)
        return True
    except Exception as exc:
        logger.error("Failed to send daily negative review report: %s", exc)
        return False
