"""
Business Rule Engine
=====================
Enforces all business rules AFTER AI analysis is complete.
The rule engine is the final authority on what action to take.
The LLM's suggestions are advisory only — rules always win.

Platform rules:
  Google 5★       → draft + auto-reply if setting ON and not sensitive
  Google 4★       → draft + auto-reply only if no negative/sensitive signal
  Google ≤3★      → draft + manager review required (no auto-reply)
  Yelp (any)      → draft + suggest only (NEVER auto-post)

Sensitive review:
  Any sensitive keyword → urgency=high, manager required, no auto-reply, escalate
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("review_system.rule_engine")

PROMPT_VERSION = "v2"   # keep in sync with ai_analysis.py

# ── Sensitive keyword patterns ────────────────────────────────────────────────
# Each pattern is case-insensitive; match = sensitive review
_SENSITIVE_PATTERNS: list[re.Pattern] = [p for p in [
    re.compile(r"\bfood\s*poison\w*\b", re.I),
    re.compile(r"\bgot\s+sick\b", re.I),
    re.compile(r"\bfell\s+sick\b", re.I),
    re.compile(r"\bmade\s+(me|us|my\s+\w+)\s+sick\b", re.I),
    re.compile(r"\ball\s+\w+\s+night\b.*sick", re.I),
    re.compile(r"\baller(gy|gic|gen)\b", re.I),
    re.compile(r"\buncooked\b", re.I),
    re.compile(r"\braw\s+(chicken|fish|meat|pork|beef|shrimp|seafood)\b", re.I),
    re.compile(r"\b(chicken|fish|meat|pork|beef|shrimp|seafood)\b.{0,40}\braw\b", re.I),
    re.compile(r"\bunsafe\s+food\b", re.I),
    re.compile(r"\bcontaminat\w*\b", re.I),
    re.compile(r"\binsect\b|\bcock?roach\b|\bbug\b|\bfly\b|\bflies\b", re.I),
    re.compile(r"\bhair\s+in\b|\bfound\s+\w*\s*hair\b", re.I),
    re.compile(r"\bdirty\s+(kitchen|plate|glass|fork|spoon|utensil)\b", re.I),
    re.compile(r"\brude\s+staff\b|\bstaff\s+(was\s+)?rude\b|\bvery\s+rude\b", re.I),
    re.compile(r"\bdiscriminat\w*\b", re.I),
    re.compile(r"\bracis[mt]\w*\b", re.I),
    re.compile(r"\bsexual\s+harass\w*\b", re.I),
    re.compile(r"\bharassment\b|\bthreat\w*\b", re.I),
    re.compile(r"\brefund\b", re.I),
    re.compile(r"\bcharged\s+twice\b", re.I),
    re.compile(r"\bovercharged\b", re.I),
    re.compile(r"\bbilling\s+(issue|error|problem)\b", re.I),
    re.compile(r"\blawsuit\b|\blegal\s+(action|threat)\b", re.I),
    re.compile(r"\bcall\s+the\s+police\b|\bcalled\s+police\b|\bpolice\b.*complaint", re.I),
    re.compile(r"\bviolence\b|\bfight\b|\bassault\b", re.I),
    re.compile(r"\bhealth\s+(department|inspector|inspection)\b", re.I),
    re.compile(r"\bfda\b|\bbbb\b|\byelp\s+review\s+team\b", re.I),
] if p]

# Keywords that suggest negative signal in an otherwise moderate review
_NEGATIVE_SIGNAL_PATTERNS: list[re.Pattern] = [p for p in [
    re.compile(r"\bdisappoint\w*\b", re.I),
    re.compile(r"\bwait(ed|ing)?\s+(too\s+)?(long|forever)\b", re.I),
    re.compile(r"\bnever\s+(coming\s+back|return)\b", re.I),
    re.compile(r"\bwould\s+not\s+recommend\b|\bdo\s+not\s+recommend\b", re.I),
    re.compile(r"\bterribl[ey]\b|\bawful\b|\bhorribl[ey]\b", re.I),
    re.compile(r"\bcold\s+food\b|\bfood\s+was\s+cold\b", re.I),
    re.compile(r"\bwrong\s+order\b|\bmissed\s+item\b", re.I),
] if p]


@dataclass
class RuleDecision:
    """Result of rule engine evaluation."""
    final_status: str           # Review lifecycle status to set
    action_type: str            # Action to log in review_actions
    auto_reply: bool            # Whether to auto-post
    should_send_email: bool     # Whether to alert manager
    urgency: str                # Forced urgency after rule checks
    is_sensitive: bool          # Whether sensitive keywords were found
    override_reason: str        # Human-readable reason for override


def check_sensitive(text: str) -> tuple[bool, list[str]]:
    """
    Scan review text for sensitive keywords.
    Returns (is_sensitive, list_of_matched_patterns).
    """
    if not text:
        return False, []
    matches = []
    for pattern in _SENSITIVE_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append(m.group(0).strip())
    return bool(matches), matches


def has_negative_signal(text: str) -> bool:
    """Return True if text contains moderate negative signals."""
    if not text:
        return False
    return any(p.search(text) for p in _NEGATIVE_SIGNAL_PATTERNS)


def evaluate(
    *,
    platform: str,
    rating: int,
    review_text: str,
    ai_analysis: dict[str, Any],
    auto_reply_setting_enabled: bool = False,
) -> RuleDecision:
    """
    Apply all business rules and return the final decision.

    Parameters
    ----------
    platform : "google" or "yelp"
    rating   : 1–5 stars
    review_text : raw review content
    ai_analysis : validated dict from ai_analysis.analyze_review_sync()
    auto_reply_setting_enabled : from review_settings.auto_reply_google_positive
    """
    text = (review_text or "").strip()
    ai_urgency = ai_analysis.get("urgency", "low")
    ai_manager = ai_analysis.get("manager_attention_required", False)
    ai_auto_reply = ai_analysis.get("auto_reply_allowed", False)

    # Step 1: Sensitive keyword scan (always overrides AI)
    sensitive, matched = check_sensitive(text)
    override_reasons: list[str] = []

    # Step 2: Force urgency high on sensitive content
    if sensitive:
        urgency = "high"
        override_reasons.append(f"sensitive keywords detected: {matched[:3]}")
    elif ai_urgency == "high" or ai_manager:
        urgency = "high"
    elif rating <= 2:
        urgency = "high"
        override_reasons.append("rating <= 2")
    elif rating == 3:
        urgency = "medium"
    else:
        urgency = ai_urgency or "low"

    # Step 3: Manager attention required?
    manager_required = (
        sensitive
        or ai_manager
        or rating <= 3
        or urgency == "high"
    )
    if rating <= 3 and not sensitive:
        override_reasons.append(f"rating {rating} <= 3 requires manager review")

    # Step 4: Auto-reply eligibility
    # RULE: Yelp NEVER auto-posts
    if platform == "yelp":
        auto_reply = False
        override_reasons.append("yelp auto-post disabled by policy")
    # RULE: Sensitive reviews never auto-reply
    elif sensitive:
        auto_reply = False
    # RULE: Manager-required reviews never auto-reply
    elif manager_required:
        auto_reply = False
    # RULE: Only 4–5 star Google with setting ON
    elif platform == "google" and rating >= 4:
        negative_signal = has_negative_signal(text)
        if negative_signal:
            auto_reply = False
            override_reasons.append("negative signal detected in otherwise positive review")
        elif not auto_reply_setting_enabled:
            auto_reply = False
            override_reasons.append("auto_reply_google_positive setting is OFF")
        else:
            auto_reply = ai_auto_reply and auto_reply_setting_enabled
    else:
        auto_reply = False

    # Step 5: Determine final review status
    if sensitive:
        final_status = "escalated"
        action_type = "escalated"
    elif manager_required and not auto_reply:
        final_status = "awaiting_approval"
        action_type = "marked_awaiting_approval"
    elif auto_reply:
        final_status = "approved"          # will transition to auto_replied after post
        action_type = "drafted"
    elif platform == "yelp":
        final_status = "analyzed"          # suggest only, shown on dashboard
        action_type = "drafted"
    else:
        final_status = "awaiting_approval"
        action_type = "marked_awaiting_approval"

    # Step 6: Email alert conditions
    should_send_email = (
        sensitive
        or manager_required
        or rating <= 3
        or urgency in ("high", "medium")
    )

    reason = "; ".join(override_reasons) if override_reasons else "rules satisfied"
    logger.info(
        f"Rule decision | platform={platform} rating={rating} "
        f"sensitive={sensitive} auto_reply={auto_reply} "
        f"status={final_status} urgency={urgency} | {reason}"
    )

    return RuleDecision(
        final_status=final_status,
        action_type=action_type,
        auto_reply=auto_reply,
        should_send_email=should_send_email,
        urgency=urgency,
        is_sensitive=sensitive,
        override_reason=reason,
    )
