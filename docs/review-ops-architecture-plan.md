# Review Ops Architecture Plan

## Architecture update proposal

The system moves from a platform-specific fetch implementation into a provider-based ingestion layer:

- `app/providers/base.py`
  Defines the provider contract, normalized review payload, and structured errors.
- `app/providers/page_provider.py`
  Shared Playwright-based page collector for operator-assisted session reuse.
- `app/providers/google_portal.py`
  Google Business portal collector using a valid staff-provided session state.
- `app/providers/yelp.py`
  Yelp collector using public page access or optional session reuse.
- `app/workers/fetch_worker.py`
  Iterates `review_sources`, validates session state, fetches normalized reviews, updates source health, and queues reply generation only for unreplied reviews.

There is no dependency on Google Business Profile review APIs in the live ingestion path. Collection is web-first and page-driven.

### Provider interface design

Every provider must implement:

- `validate_session() -> tuple[bool, str]`
  Returns whether the session is usable and the resulting session state label.
- `fetch_reviews() -> list[ProviderReview]`
  Returns normalized reviews with owner-reply detection already populated.

Normalized `ProviderReview` fields:

- `external_review_id`
- `platform`
- `source_url`
- `reviewer_name`
- `rating`
- `review_text`
- `review_date`
- `has_owner_reply`
- `detected_owner_reply_text`
- `detected_owner_reply_at`
- `raw_payload`

Structured provider errors:

- `ProviderConfigError`
- `ProviderAuthRequiredError`
- `ProviderFetchError`

## DB migration plan

Implemented in [002_review_ops_phase1.py](/E:/Project/Master/review-automation-system/alembic/versions/002_review_ops_phase1.py).

### New tables

- `review_sources`
- `auth_sessions`
- `reply_suggestions`

### Expanded tables

- `reviews`
  Added `external_review_id`, `source_id`, `source_url`, `detected_owner_reply_text`, `detected_owner_reply_at`, `has_owner_reply`, `raw_payload`, `collected_at`, `first_seen_at`, `last_seen_at`.
- `replies`
  Added `tone_mode`, `confidence_note`, `reason_summary`, `issue_tags`, `risk_flags`.
- `jobs`
  Added `source_id`.

### Data backfill

- Existing `platform_review_id` copied into `external_review_id`.
- Existing reply detection copied into `has_owner_reply`.
- Existing raw JSON copied into `raw_payload`.
- Existing timestamps backfilled into `collected_at`, `first_seen_at`, `last_seen_at`.
- Existing location Google/Yelp settings materialized into `review_sources`.
- Existing Google sources are backfilled to web collector URLs in [004_web_source_urls_only.py](/E:/Project/Master/review-automation-system/alembic/versions/004_web_source_urls_only.py).

## Proposed folder and file changes

### Added

- [app/models/review_source.py](/E:/Project/Master/review-automation-system/app/models/review_source.py)
- [app/models/auth_session.py](/E:/Project/Master/review-automation-system/app/models/auth_session.py)
- [app/models/reply_suggestion.py](/E:/Project/Master/review-automation-system/app/models/reply_suggestion.py)
- [app/providers/base.py](/E:/Project/Master/review-automation-system/app/providers/base.py)
- [app/providers/page_provider.py](/E:/Project/Master/review-automation-system/app/providers/page_provider.py)
- [app/providers/google_portal.py](/E:/Project/Master/review-automation-system/app/providers/google_portal.py)
- [app/providers/yelp.py](/E:/Project/Master/review-automation-system/app/providers/yelp.py)
- [app/providers/registry.py](/E:/Project/Master/review-automation-system/app/providers/registry.py)
- [app/services/review_ops.py](/E:/Project/Master/review-automation-system/app/services/review_ops.py)
- [alembic/versions/002_review_ops_phase1.py](/E:/Project/Master/review-automation-system/alembic/versions/002_review_ops_phase1.py)
- [docs/review-ops-architecture-plan.md](/E:/Project/Master/review-automation-system/docs/review-ops-architecture-plan.md)

### Updated

- [app/workers/fetch_worker.py](/E:/Project/Master/review-automation-system/app/workers/fetch_worker.py)
- [app/workers/reply_worker.py](/E:/Project/Master/review-automation-system/app/workers/reply_worker.py)
- [app/routes/api.py](/E:/Project/Master/review-automation-system/app/routes/api.py)
- [app/routes/dashboard.py](/E:/Project/Master/review-automation-system/app/routes/dashboard.py)
- [app/services/ai_reply.py](/E:/Project/Master/review-automation-system/app/services/ai_reply.py)
- `app/templates/*`
- `app/static/css/style.css`
- `app/static/js/dashboard.js`

## API endpoints to add or update

### Updated

- `GET /api/stats`
  Returns operations-facing summary cards.
- `GET /api/reviews`
  Supports store, platform, date preset, custom date range, rating, and status filters.
- `GET /api/reviews/{id}`
  Returns review detail, source info, suggestion history, and job history.
- `POST /api/reviews/{id}/approve`
  Queues operator-assisted approval flow.
- `POST /api/fetch/trigger`
  Supports optional `location_id`, `platform`, and `source_id`.
- `GET /api/jobs`
  Includes `source_id`.

### Added

- `GET /api/sources`
  Returns review source configuration and session health.
- `POST /api/reviews/{id}/suggestions/regenerate`
  Regenerates a suggestion for a selected tone mode.

### Recommended next endpoints

- `POST /api/reviews/{id}/mark-handled`
- `POST /api/reviews/bulk/regenerate`
- `POST /api/reviews/bulk/export`
- `POST /api/sources/{id}/auth-session`
- `POST /api/sources/{id}/validate-session`
- `GET /api/admin/tone-config`
- `PATCH /api/admin/tone-config`

## Dashboard page and component list

### Current pages after Phase 1

- `/`
  Summary cards, source health, recent attention reviews, recent jobs.
- `/reviews`
  Queue-first review workspace with filters and row-level open action.
- `/reviews/{id}`
  Review detail page with source metadata, current suggestion, suggestion history, and job history.
- `/locations`
  Location-level source health overview.

### Recommended Phase 2-3 components

- Review detail drawer or modal from queue page
- Bulk selection toolbar
- Export dialog
- Source auth/session admin panel
- Tone configuration admin screen
- Alert and escalation configuration page

## Collector implementation notes

### Google collector

- Uses `GoogleReviewsPortalProvider`.
- Must never attempt to bypass login, CAPTCHA, MFA, or other platform protections.
- Requires an authorized staff-provided session reference stored in `auth_sessions.session_reference`.
- Session reference should point to a Playwright storage-state JSON file or another managed secure session artifact.
- If no valid session exists, the source is marked `reauth_required`.
- Selectors should stay configurable inside `review_sources.settings`.
- The collector should only read visible review data and merchant response state.
- Posting remains operator-assisted for now.
- Legacy Google OAuth/API modules have been removed from the active code path.

### Yelp collector

- Uses `YelpReviewsProvider`.
- Can run publicly when the page is accessible without login.
- May reuse a valid staff session when needed, but must still fail safely on CAPTCHA or blocked access.
- CAPTCHA or anti-bot UI should mark the source as failed or reauth-required, not trigger bypass attempts.
- Selector overrides should stay configurable inside `review_sources.settings`.

### Incremental sync behavior

- Sync cadence:
  - lightweight sync every 2-4 hours
  - fuller reconciliation daily
- Record `first_seen_at`, `last_seen_at`, and `collected_at`.
- Update `has_owner_reply` whenever a reply appears later on the source page.
- Queue AI suggestion generation only when:
  - no owner reply is visible on source, and
  - no local reply has already been posted.

## Definition of unreplied

Use this rule consistently in API, UI, and jobs:

- `review.has_owner_reply` must be false
- there must be no local `Reply` with status `posted`

Operational status mapping:

- `unreplied`
- `pending_review`
- `approved`
- `posted`
- `replied`
- `failed`

## Security and compliance notes

- Do not hardcode credentials.
- Keep API keys and SMTP credentials in environment variables.
- Persist only secure session references, not raw passwords.
- Session reference storage should be encrypted or stored in a managed secret store before production rollout.
- Log sensitive actions such as session updates, manual approvals, and admin configuration edits.
- Add RBAC in a follow-up phase for `admin`, `manager`, `operator`, and `viewer`.

## Risks, assumptions, and blockers

### Risks

- Google portal DOM can change without notice.
- Session-backed collection is brittle if staff do not refresh sessions promptly.
- CAPTCHA and anti-automation checks can interrupt collection.
- Existing `jobs` and `replies` tables are still serving legacy responsibilities, so Phase 2 should continue separating operational posting from suggestion history.

### Assumptions

- Authorized staff can provide and rotate session-state files compliantly.
- Review volume is moderate enough for Jinja dashboard pages in the short term.
- PostgreSQL is the source of truth for review and suggestion state.

### Current blockers

- No secure secret-manager-backed session storage yet.
- No automated posting flow for portal-based sources, by design.

## Testing checklist

- Run Alembic upgrade on a fresh database.
- Run Alembic upgrade on a database with existing v1 data and verify source backfill.
- Verify `/api/reviews` filters for store, platform, status, preset dates, and custom dates.
- Verify reviews with visible owner replies are excluded from the default queue.
- Verify failed or expired sources appear in dashboard summary cards.
- Verify regenerate suggestion endpoint produces new `reply_suggestions` rows.
- Verify existing queue processing still creates `replies` records.
- Verify negative review alert flow still works.
- Verify responsive behavior for dashboard, queue, and review detail pages.
- Verify a missing or expired session marks the source `reauth_required`.

## Implementation plan by phase

### Phase 1

- Remove hard Google API dependency from fetch flow.
- Introduce provider abstraction and source/session schema.
- Add unreplied-first filters and dashboard updates.
- Preserve current FastAPI, Jinja, PostgreSQL, Redis/rq structure.

### Phase 2

- Add admin session bootstrap and validation screens.
- Harden Google and Yelp selectors per real source pages.
- Add review detail drawer/modal and better source debugging artifacts.
- Add manual sync per location, platform, and source in the UI.

### Phase 3

- Add bulk actions, export, and queue triage improvements.
- Add tone configuration, escalation rules, and alert recipient management.
- Add richer AI classification and operator editing workflows.

### Phase 4

- Add RBAC, audit logs, secure session storage, and production runbooks.
- Expand test coverage and retry controls.
- Add monitoring and deployment documentation.

## Rollout plan

1. Apply migration `002`.
2. Seed or verify `review_sources` for each location.
3. Configure `review_sources.settings` selectors where the defaults are insufficient.
4. Upload secure session references for Google or any Yelp source that requires them.
5. Run manual fetch for one pilot location and review dashboard results.
6. Validate unreplied filtering and suggestion generation with staff.
7. Expand to all locations.
8. Enable scheduled sync cadence.
9. Implement admin session maintenance before production scale-up.

## Final estimate by phase

- Phase 1: 2-4 developer days
- Phase 2: 4-6 developer days
- Phase 3: 4-5 developer days
- Phase 4: 3-5 developer days

Total estimated effort: 13-20 developer days, depending on the amount of real-world selector tuning and admin workflow polish required.
