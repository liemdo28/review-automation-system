# Review Automation System UAT Plan

## Objective

Validate that `review-automation-system` is usable, understandable, and valuable for real business operations.

This is not a technical test plan. It is a real-world user acceptance test for:

- store managers
- operations staff
- owners or executives

## Product Standard

The product succeeds only when a user can:

1. open the app
2. understand what it does quickly
3. find unreplied reviews without training
4. complete review work with confidence
5. understand what to do when something fails

## Test Personas

### Persona A — Store Manager

- manages 1–2 stores
- checks reviews daily
- replies to customers

### Persona B — Operations Staff

- handles multiple stores
- processes reviews in batches
- prepares replies and may approve them

### Persona C — Owner / CEO

- wants a high-level view
- checks unresolved reviews
- cares about priorities and system health, not detailed operations

## UAT Success Criteria

The system passes UAT only if:

- a new user understands the dashboard within 30–60 seconds
- unreplied reviews are obvious
- daily workflow is smooth and not confusing
- failures are understandable
- the tool feels faster and safer than manual handling

## UAT Flows

### Flow 1 — First-time user experience

#### Scenario

The user opens the app without reading documentation.

#### Steps

1. Open the application.
2. Look at the first screen only.
3. Try to identify the purpose of the system.

#### Questions

- Do you understand what this system does?
- Can you identify stores?
- Can you identify Google and Yelp sources?
- Can you identify pending reviews?
- Do you know what to do next?

#### Expected result

- The product purpose is obvious immediately.
- Unreplied or pending reviews are easy to find.
- Navigation feels business-focused, not developer-focused.

#### Fail if

- the user asks “what should I do?”
- the user cannot find pending reviews
- the product feels like a dev console instead of an operations tool

### Flow 2 — Daily operations

#### Scenario

The user logs in to process today’s reviews.

#### Steps

1. Open dashboard or queue.
2. Find reviews needing replies.
3. Open a review.
4. Read the content.
5. generate, edit, or review the suggested reply
6. approve, save, or continue

#### Expected result

- The flow is smooth and obvious.
- Actions are understandable.
- Store/source context is always clear.
- The process feels faster than manual handling.

#### Fail if

- unreplied reviews are hard to find
- too many clicks are needed to finish one review
- button meanings are unclear

### Flow 3 — Multi-store handling

#### Scenario

The user manages multiple stores.

#### Steps

1. Open dashboard or queue.
2. Filter by one store.
3. Switch to another store.
4. Compare pending work by store.

#### Expected result

- stores are clearly separated
- switching is easy
- no mixing of store data

#### Fail if

- the user is unsure which store they are viewing
- reviews appear under the wrong store
- filters feel awkward or unreliable

### Flow 4 — Filtering and control

#### Scenario

The user wants to narrow down work.

#### Steps

1. Filter by store.
2. Filter by source.
3. Filter by star rating.
4. Filter by date.
5. Filter by unreplied or needs-attention status.

#### Expected result

- filters are intuitive
- results update correctly
- counts and visible items feel trustworthy

#### Fail if

- filters feel technical
- the user is unsure whether a filter is active
- results do not match expectation

### Flow 5 — Review understanding

#### Scenario

The user opens one review detail.

#### Expected visible information

- review text
- rating
- reviewer name
- review date
- source
- reply status

#### Fail if

- any important information is missing
- the user has to guess what happened or what state the review is in

### Flow 6 — Reply workflow

#### Scenario

The user works on a reply.

#### Steps

1. Open an unreplied review.
2. Generate or inspect draft.
3. Edit if needed.
4. Save, approve, or continue.

#### Expected result

- the draft is understandable
- editing is easy
- actions are confidence-building

#### Fail if

- the draft feels irrelevant or robotic
- editing is hard
- save / approve / send meanings are unclear

### Flow 7 — Error handling

#### Scenario

Something goes wrong.

#### Examples

- sync fails
- source needs login
- source is blocked

#### Questions

- Does the user understand what failed?
- Does the user know what to do next?

#### Expected result

- error message is clear
- next action is obvious
- message avoids technical jargon where possible

#### Fail if

- the user needs backend logs to understand the problem
- the user is stuck
- the UI hides the failure

### Flow 8 — Job and sync visibility

#### Scenario

The user wants to confirm the system is working.

#### Expected result

The user can quickly understand:

- last successful sync
- last failed sync
- review counts
- whether the system is healthy

#### Fail if

- the user cannot tell whether sync worked
- failures are not visible
- status is too technical

### Flow 9 — Speed and fatigue

#### Scenario

The user processes 10–20 reviews.

#### Expected result

- transitions feel smooth
- repeated actions are efficient
- the tool reduces fatigue instead of adding friction

#### Fail if

- loading feels slow
- actions feel repetitive
- the user feels slower than manual work

### Flow 10 — Owner / CEO view

#### Scenario

The owner opens the system for 10–15 seconds.

#### Expected result

The owner can instantly see:

- how many reviews need attention
- which stores have issues
- whether the system is working

#### Fail if

- too much detail is shown first
- priorities are unclear
- health/status is not obvious

## UX Scoring

Each tester should score 1–10 for:

- ease of understanding
- speed of workflow
- UI clarity
- error clarity
- multi-store usability
- overall confidence

## Critical UAT Fail Conditions

The product must not be approved if:

- users cannot find unreplied reviews quickly
- users do not understand what action to take next
- store/source confusion exists
- reply workflow is unclear
- errors are hidden or confusing
- the workflow feels slower than manual work

## Final UAT Decision

Each tester must choose one:

- APPROVED
- APPROVED WITH MINOR IMPROVEMENTS
- REJECTED (major fixes required)

## Core Product Insight

If technical QA passes but UAT fails, the product will still fail in real life.

The product should optimize for:

- clarity over complexity
- workflow over feature count
- visibility over hidden logic

## Final Standard

Success means:

User opens app → sees work clearly → completes work confidently → trusts the system.
