# Review Automation System QA Test Plan

## Objective

Run a full QA pass against `review-automation-system` to validate:

- source connection reliability
- review pull accuracy
- unreplied-only filtering
- date filter correctness
- dashboard and inbox usability
- reply workflow safety
- error visibility
- stability under realistic load

This plan is intended for QA, developers, product owners, and review operations staff.

## Product Goal

The system should allow operators to:

1. connect Google Business and Yelp review sources
2. validate source/session health
3. sync reviews safely
4. prioritize unreplied reviews
5. filter by date and source
6. inspect review details and AI suggestions
7. approve or automate replies safely
8. understand failures directly from the UI

## Scope

### In scope

- app launch and environment validation
- source setup and auth/session handling
- review ingestion and normalization
- unreplied review detection
- date filtering
- dashboard and review queue UX
- reply generation and approval workflow
- job history and error monitoring
- multi-store behavior
- load and reliability testing
- role and secret-handling checks where supported

### Out of scope

- legal/compliance sign-off
- third-party provider SLA guarantees
- billing or unrelated admin systems

## Test Environments

### Browsers

- Chrome latest
- Edge latest

### Operating systems

- Windows 10/11
- macOS optional if the team expects operator support there

### Runtime modes

- local development
- staging
- production-like staging with realistic data

### Network conditions

- normal connection
- slow/throttled connection
- temporary disconnect/reconnect

## Required Test Data

Prepare at least:

- 1 Google-only store
- 1 Yelp-only store
- 1 store connected to both Google and Yelp
- 1 store with many reviews
- 1 store with no recent reviews
- 1 store with already replied reviews
- 1 store with unreplied reviews only

Review fixtures should include:

- 1-star through 5-star reviews
- short reviews
- long reviews
- minimal text reviews
- old and new reviews
- replied and unreplied reviews
- duplicate-looking reviews
- emoji, accented text, Vietnamese, and multilingual content

## Execution Rules

For every failed test capture:

- environment
- store
- source
- test case ID
- screenshot
- console/server log excerpt if relevant
- exact expected result
- actual result
- suspected impact

Severity scale:

- Critical
- High
- Medium
- Low

## Functional Test Matrix

### Module A — App launch and config

- TC-A01 app loads without blank screen or fatal layout break
- TC-A02 missing required env key fails clearly without secret leakage

### Module B — Authentication and source sessions

- TC-B01 Google source validates with a healthy session
- TC-B02 Yelp source validates with a healthy session
- TC-B03 expired session is detected and surfaced as re-auth required
- TC-B04 captcha/block state is not misreported as “no reviews found”

### Module C — Store management

- TC-C01 stores list loads with source status and last sync data
- TC-C02 store-source mapping is correct
- TC-C03 disabled store is skipped by global sync

### Module D — Review pulling

- TC-D01 single store / single source sync succeeds
- TC-D02 dual-source store sync processes both Google and Yelp correctly
- TC-D03 zero-new-review result is shown as success, not failure
- TC-D04 repeated sync does not duplicate reviews
- TC-D05 pagination handles large review sets
- TC-D06 partial page failure fails or retries safely with clear logs

### Module E — Review data integrity

Validate normalization of:

- source
- store_id
- store_name
- review_id
- author_name
- rating
- review_text
- review_date
- has_reply
- reply_text
- reply_date
- review_url
- pulled_at

Additional checks:

- TC-E02 special characters render correctly
- TC-E03 long review content truncates safely in list view and expands in detail view

### Module F — Reply status detection

- TC-F01 replied reviews are marked `has_reply = true`
- TC-F02 unreplied reviews are marked `has_reply = false`
- TC-F03 mixed datasets filter correctly under unreplied-only view
- TC-F04 slow or partial page load does not create false unreplied positives

### Module G — Date filters

- TC-G01 custom date range
- TC-G02 last 1 day
- TC-G03 last 3 days
- TC-G04 last 7 days
- TC-G05 last 30 days
- TC-G06 cross-midnight timezone behavior
- TC-G07 invalid date input validation

### Module H — Dashboard and inbox UX

- TC-H01 first-time user can identify stores, sources, pending work, failures, and next action quickly
- TC-H02 filters, sorting, pagination, and reset all work correctly
- TC-H03 review detail shows review, source, rating, date, and actions clearly
- TC-H04 empty states are clean and explain why no data is shown
- TC-H05 failed syncs are obvious and actionable

### Module I — Reply workflow

- TC-I01 generate AI draft
- TC-I02 edit draft manually without accidental overwrite
- TC-I03 approve and reject flow updates status correctly
- TC-I04 send reply flow targets the correct review and prevents duplicate sends
- TC-I05 retry after send failure is safe

### Module J — Jobs, logs, monitoring

- TC-J01 job history records ID, store, source, timestamps, status, result summary, and error summary
- TC-J02 failed job logs are detailed enough without leaking secrets
- TC-J03 stale running jobs are detected and do not hang forever in UI

### Module K — Multi-store behavior

- TC-K01 sync all stores without one failure collapsing all others
- TC-K02 source isolation keeps Google and Yelp failures independent when possible
- TC-K03 large multi-store result sets do not corrupt data or destroy UX

### Module L — Performance and stress

- TC-L01 import 500 / 1,000 / 5,000 reviews if supported
- TC-L02 repeated sync cycle does not create leak or duplicate buildup
- TC-L03 slow network does not cause false empty-state reporting

### Module M — Security and permissions

- TC-M01 secrets do not leak through UI, logs, or payloads
- TC-M02 role restrictions work in both UI and backend if role model is enabled
- TC-M03 direct API access to restricted actions is rejected

## Bug Severity Rules

### Critical

- source connection completely broken
- wrong review replied
- duplicate reply posting
- severe data corruption
- credential/session leakage
- replied/unreplied classification fundamentally wrong

### High

- sync often fails
- date filters inaccurate
- duplicate imports
- dashboard hides critical failure
- multi-store mapping wrong

### Medium

- unclear UX
- missing validation
- inconsistent counts
- partial logging
- workflow-slowing layout issues

### Low

- wording
- alignment
- cosmetic styling
- non-blocking UI polish

## Deliverables

QA execution should produce:

1. test execution report
2. bug report list with severity
3. UX findings report
4. release recommendation:
   - Ready for release
   - Ready with minor fixes
   - Not ready, major fixes required

## Acceptance Criteria

The product is acceptable only if:

- source connection works reliably
- store-source mapping is accurate
- review pull works across supported sources
- unreplied reviews are detected correctly
- date filters are accurate
- duplicates are controlled
- failed syncs are clearly visible
- new users understand the workflow without training
- logs are usable without server shell access
- the system remains stable under realistic multi-store load

## Recommended Execution Order

1. app launch and config
2. source connection
3. single-store sync
4. review integrity validation
5. unreplied filtering validation
6. date filter validation
7. dashboard and queue UX
8. reply workflow
9. logs and job history
10. multi-store sync
11. stress testing
12. security and permission review
