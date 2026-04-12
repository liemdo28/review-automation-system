"""
Email Alert Service
====================
Sends manager/admin email notifications for:
  - Low-rating reviews (≤3 stars)
  - Sensitive / high-urgency reviews
  - Auto-publish failures
  - Repeated fetch job failures
  - AI output failure (fell back to manual review)

Renders a clean HTML + plain-text multi-part email with all required fields.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.config import settings

logger = logging.getLogger("review_system.email_alert")

# ── Template helpers ──────────────────────────────────────────────────────────

def _stars_html(rating: int) -> str:
    filled = "★" * rating
    empty = "☆" * (5 - rating)
    color = "#4ade80" if rating >= 4 else "#fbbf24" if rating == 3 else "#f87171"
    return f'<span style="color:{color};font-size:18px">{filled}{empty}</span>'


def _urgency_badge(urgency: str) -> str:
    colors = {"high": "#f87171", "medium": "#fbbf24", "low": "#4ade80"}
    bg = colors.get(urgency, "#888")
    return (
        f'<span style="background:{bg};color:#000;padding:2px 8px;'
        f'border-radius:4px;font-weight:bold;font-size:12px">'
        f'{urgency.upper()}</span>'
    )


def _issue_badges(issue_types: list[str]) -> str:
    if not issue_types:
        return "<em>none detected</em>"
    labels = [i.replace("_", " ").title() for i in issue_types]
    return " ".join(
        f'<span style="background:#333;color:#ddd;padding:2px 6px;'
        f'border-radius:4px;font-size:11px">{label}</span>'
        for label in labels
    )


# ── HTML email body ───────────────────────────────────────────────────────────

def _build_review_alert_html(
    *,
    subject: str,
    platform: str,
    store: str,
    rating: int,
    reviewer: str,
    review_text: str,
    urgency: str,
    issue_types: list[str],
    summary: str,
    suggested_reply: str,
    review_url: str,
    review_id: int,
    recommended_action: str,
    is_sensitive: bool,
    app_url: str,
) -> str:
    sensitive_banner = ""
    if is_sensitive:
        sensitive_banner = (
            '<div style="background:#f87171;color:#000;padding:12px;'
            'border-radius:6px;font-weight:bold;margin-bottom:16px">'
            "⚠️  SENSITIVE REVIEW — Do NOT auto-reply. Requires immediate management attention."
            "</div>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:24px;margin:0">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">

  <!-- Header -->
  <div style="background:#1a1a2e;color:#fff;padding:20px 24px">
    <h1 style="margin:0;font-size:20px">Review Alert — {store}</h1>
    <p style="margin:4px 0 0;color:#aaa;font-size:13px">{subject}</p>
  </div>

  <!-- Body -->
  <div style="padding:24px">
    {sensitive_banner}

    <!-- Meta row -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
      <tr>
        <td style="padding:8px 0;color:#666;width:140px">Platform</td>
        <td style="padding:8px 0;font-weight:bold;text-transform:capitalize">{platform}</td>
      </tr>
      <tr style="background:#f9f9f9">
        <td style="padding:8px 0;color:#666">Store</td>
        <td style="padding:8px 0;font-weight:bold">{store}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666">Reviewer</td>
        <td style="padding:8px 0">{reviewer}</td>
      </tr>
      <tr style="background:#f9f9f9">
        <td style="padding:8px 0;color:#666">Rating</td>
        <td style="padding:8px 0">{_stars_html(rating)} ({rating}/5)</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666">Urgency</td>
        <td style="padding:8px 0">{_urgency_badge(urgency)}</td>
      </tr>
      <tr style="background:#f9f9f9">
        <td style="padding:8px 0;color:#666">Issues</td>
        <td style="padding:8px 0">{_issue_badges(issue_types)}</td>
      </tr>
    </table>

    <!-- Review text -->
    <div style="margin-bottom:20px">
      <h3 style="margin:0 0 8px;font-size:14px;color:#333">Review</h3>
      <div style="background:#f0f4ff;border-left:4px solid #6c63ff;padding:12px;border-radius:4px;font-style:italic;color:#444">
        {review_text or "<em>(No written comment)</em>"}
      </div>
    </div>

    <!-- AI summary -->
    <div style="margin-bottom:20px">
      <h3 style="margin:0 0 8px;font-size:14px;color:#333">AI Summary</h3>
      <p style="margin:0;color:#555">{summary or "No summary available."}</p>
    </div>

    <!-- Suggested reply -->
    <div style="margin-bottom:20px">
      <h3 style="margin:0 0 8px;font-size:14px;color:#333">Suggested Reply</h3>
      <div style="background:#f0fff4;border-left:4px solid #4ade80;padding:12px;border-radius:4px;color:#444">
        {suggested_reply or "<em>No reply drafted yet.</em>"}
      </div>
    </div>

    <!-- Recommended action -->
    <div style="background:#fff8e1;border:1px solid #fbbf24;padding:12px;border-radius:6px;margin-bottom:24px">
      <strong>Recommended Action:</strong> {recommended_action}
    </div>

    <!-- CTA buttons -->
    <div style="margin-bottom:24px">
      <a href="{app_url}/reviews/{review_id}"
         style="display:inline-block;background:#6c63ff;color:#fff;padding:10px 20px;
                border-radius:6px;text-decoration:none;font-weight:bold;margin-right:8px">
        View in Dashboard
      </a>
      {"" if not review_url else f'<a href="{review_url}" style="display:inline-block;background:#333;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">View on {platform.title()}</a>'}
    </div>

    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="color:#aaa;font-size:12px;margin:0">
      Review #{review_id} · Sent by Review Automation System ·
      {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    </p>
  </div>
</div>
</body>
</html>"""


def _build_review_alert_text(
    *,
    platform: str,
    store: str,
    rating: int,
    reviewer: str,
    review_text: str,
    urgency: str,
    issue_types: list[str],
    summary: str,
    suggested_reply: str,
    review_url: str,
    review_id: int,
    recommended_action: str,
    is_sensitive: bool,
    app_url: str,
) -> str:
    sensitive_line = "\n⚠️  SENSITIVE REVIEW — DO NOT AUTO-REPLY\n" if is_sensitive else ""
    issues = ", ".join(i.replace("_", " ") for i in issue_types) if issue_types else "none"
    return f"""{sensitive_line}
Platform:    {platform.title()}
Store:       {store}
Reviewer:    {reviewer}
Rating:      {"★" * rating} ({rating}/5)
Urgency:     {urgency.upper()}
Issues:      {issues}

Review:
{review_text or "(No text)"}

AI Summary:
{summary or "N/A"}

Suggested Reply:
{suggested_reply or "N/A"}

Recommended Action: {recommended_action}

Dashboard: {app_url}/reviews/{review_id}
{f"Review URL: {review_url}" if review_url else ""}

---
Review #{review_id} · Review Automation System
"""


# ── Send function ─────────────────────────────────────────────────────────────

def _send_email(
    *,
    to_addr: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> bool:
    """Send a multi-part HTML+text email. Returns True on success."""
    if not settings.smtp_user or not to_addr:
        logger.warning("SMTP not configured or no recipient — skipping email")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.alert_email_from
    msg["To"] = to_addr
    msg["Subject"] = subject

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info(f"Alert email sent to {to_addr} | {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_review_alert(
    *,
    to_email: str,
    platform: str,
    store: str,
    rating: int,
    reviewer: str,
    review_text: str,
    urgency: str,
    issue_types: list[str],
    summary: str,
    suggested_reply: str,
    review_url: str = "",
    review_id: int,
    is_sensitive: bool = False,
    app_url: str = "http://localhost:8000",
) -> bool:
    """Send a rich review alert email to the manager."""
    if is_sensitive:
        recommended_action = (
            "This review is sensitive. DO NOT auto-reply. "
            "Review the content privately and respond carefully via the dashboard."
        )
    elif rating <= 2:
        recommended_action = (
            "Please review this negative feedback promptly. "
            "Edit the suggested reply if needed and post from the dashboard."
        )
    elif rating == 3:
        recommended_action = (
            "Review the suggested reply and post it from the dashboard when ready."
        )
    else:
        recommended_action = (
            "Review the AI-drafted reply and approve or edit it from the dashboard."
        )

    subject = (
        f"{'🚨 SENSITIVE' if is_sensitive else f'[{rating}★]'} "
        f"Review Alert — {store} ({platform.title()})"
    )

    html_body = _build_review_alert_html(
        subject=subject,
        platform=platform,
        store=store,
        rating=rating,
        reviewer=reviewer,
        review_text=review_text,
        urgency=urgency,
        issue_types=issue_types,
        summary=summary,
        suggested_reply=suggested_reply,
        review_url=review_url,
        review_id=review_id,
        recommended_action=recommended_action,
        is_sensitive=is_sensitive,
        app_url=app_url,
    )
    text_body = _build_review_alert_text(
        platform=platform,
        store=store,
        rating=rating,
        reviewer=reviewer,
        review_text=review_text,
        urgency=urgency,
        issue_types=issue_types,
        summary=summary,
        suggested_reply=suggested_reply,
        review_url=review_url,
        review_id=review_id,
        recommended_action=recommended_action,
        is_sensitive=is_sensitive,
        app_url=app_url,
    )

    return _send_email(to_addr=to_email, subject=subject, html_body=html_body, text_body=text_body)


def send_publish_failure_alert(
    *,
    to_email: str,
    platform: str,
    store: str,
    review_id: int,
    error_message: str,
    app_url: str = "http://localhost:8000",
) -> bool:
    """Alert manager when auto-publish to Google fails."""
    subject = f"[PUBLISH FAILED] {platform.title()} Reply — {store}"
    html_body = f"""<div style="font-family:Arial,sans-serif;padding:20px">
<h2 style="color:#f87171">Auto-Publish Failed</h2>
<p><strong>Platform:</strong> {platform.title()}</p>
<p><strong>Store:</strong> {store}</p>
<p><strong>Review ID:</strong> #{review_id}</p>
<p><strong>Error:</strong> <code style="background:#f5f5f5;padding:4px">{error_message}</code></p>
<p>The reply was NOT posted. Please log in to the dashboard and post manually.</p>
<a href="{app_url}/reviews/{review_id}" style="background:#6c63ff;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none">View Review</a>
</div>"""
    text_body = (
        f"Auto-Publish Failed\n"
        f"Platform: {platform}\nStore: {store}\nReview #{review_id}\n"
        f"Error: {error_message}\n"
        f"Please post the reply manually at {app_url}/reviews/{review_id}"
    )
    return _send_email(to_addr=to_email, subject=subject, html_body=html_body, text_body=text_body)


def send_fetch_failure_alert(
    *,
    to_email: str,
    platform: str,
    store: str,
    error_message: str,
    consecutive_failures: int,
    app_url: str = "http://localhost:8000",
) -> bool:
    """Alert admin when fetch jobs repeatedly fail."""
    subject = f"[FETCH FAILED ×{consecutive_failures}] {platform.title()} — {store}"
    html_body = f"""<div style="font-family:Arial,sans-serif;padding:20px">
<h2 style="color:#fbbf24">Fetch Job Failure</h2>
<p><strong>Platform:</strong> {platform.title()}</p>
<p><strong>Store:</strong> {store}</p>
<p><strong>Consecutive Failures:</strong> {consecutive_failures}</p>
<p><strong>Error:</strong> <code style="background:#f5f5f5;padding:4px">{error_message}</code></p>
<p>Reviews may not be coming in from this source. Please check credentials and API access.</p>
<a href="{app_url}" style="background:#6c63ff;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none">Open Dashboard</a>
</div>"""
    text_body = (
        f"Fetch Job Failure\n"
        f"Platform: {platform}\nStore: {store}\n"
        f"Consecutive Failures: {consecutive_failures}\n"
        f"Error: {error_message}\n"
        f"Dashboard: {app_url}"
    )
    return _send_email(to_addr=to_email, subject=subject, html_body=html_body, text_body=text_body)


# Legacy shim so existing code that calls send_low_rating_alert() still works
def send_low_rating_alert(
    reviewer_name: str,
    rating: int,
    review_text: str,
    suggested_reply: str,
    restaurant_name: str,
    location: str,
    review_id: int,
) -> bool:
    return send_review_alert(
        to_email=settings.alert_email_to,
        platform="unknown",
        store=f"{restaurant_name} ({location})",
        rating=rating,
        reviewer=reviewer_name,
        review_text=review_text,
        urgency="high" if rating <= 2 else "medium",
        issue_types=[],
        summary="",
        suggested_reply=suggested_reply,
        review_url="",
        review_id=review_id,
        is_sensitive=False,
    )
