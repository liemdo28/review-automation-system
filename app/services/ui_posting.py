from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings


def ui_posting_artifact_dir(review_id: int, *, step: str | None = None) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{step}" if step else ""
    directory = Path(settings.ui_posting_artifact_dir) / f"review-{review_id}-{timestamp}{suffix}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def reply_preview_hash(reply_text: str) -> str:
    normalized = " ".join((reply_text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


async def capture_failure_artifacts(page, *, review_id: int, step: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    details = dict(details or {})
    artifact_dir = ui_posting_artifact_dir(review_id, step=step)
    screenshot_path = artifact_dir / "failure.png"
    html_path = artifact_dir / "page.html"

    try:
        await page.screenshot(path=str(screenshot_path), full_page=True)
        details["screenshot_path"] = str(screenshot_path)
    except Exception:
        details["screenshot_path"] = None

    try:
        html_path.write_text(await page.content(), encoding="utf-8")
        details["html_snapshot_path"] = str(html_path)
    except Exception:
        details["html_snapshot_path"] = None

    return details
