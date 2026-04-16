# Current QA Readiness Assessment

## Snapshot

This document reflects the current repository readiness based on code audit, startup hardening, and automated tests available in the repo.

## What is already in place

- FastAPI + Jinja2 app boot structure
- PostgreSQL + Redis docker services
- Alembic migrations
- Playwright-based provider architecture
- APScheduler in-process job loop
- startup scripts with clearer failure handling
- minimum automated tests for:
  - health API
  - stats API
  - review queue API behavior
  - auto-reply policy
  - review matcher
  - session resolution
  - seed logic

## Verified automated status

- `python -m compileall app scripts tests`: passed
- `pytest tests -q`: 17 passed

## What is still not fully validated

The following still require manual QA or staging validation:

- Google provider end-to-end session bootstrap
- Yelp provider end-to-end session bootstrap
- real browser posting flow in live session state
- fresh blank database migration on a clean machine
- full docker boot on operator workstation
- realistic multi-store sync under real data volume
- slow network / reconnect behavior
- blocked/captcha/provider-UI-change scenarios
- SMTP alerting through real mail infrastructure

## Known risk areas

### Provider fragility

Google and Yelp flows remain UI/session driven. Selectors, session health, geo/IP restrictions, and provider page changes can still break sync or posting.

### Runtime environment sensitivity

Docker, Postgres, Redis, Playwright Chromium, and venv state must all be healthy. Startup scripts are improved, but workstation drift is still a major operational risk.

### Manual QA gap

Automated tests now cover core logic and some route behavior, but they do not replace browser-level QA against real provider pages.

### Time handling

Date logic has test coverage, but timezone and cross-midnight behavior still needs staging verification with realistic source timestamps.

## Current recommendation

### Release classification

Ready with major manual QA still required before calling the system production-ready.

### Practical interpretation

- good enough to continue internal hardening and controlled staging use
- not yet ready to claim full production reliability for operators without staged browser/provider QA

## Immediate next QA priorities

1. run the full manual QA plan in `docs/qa-test-plan.md`
2. record findings using `docs/qa-execution-report-template.md`
3. validate:
   - source login and session reuse
   - single-store and multi-store sync
   - unreplied-only logic
   - date presets
   - queue UX for new users
   - real reply approval/posting outcomes
