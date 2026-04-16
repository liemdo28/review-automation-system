# Review Automation System — Product Improvement Blueprint (V4)

## Vision

Transform the product from:

> a tool that pulls reviews

Into:

> a centralized Reputation Operations Platform

Positioned inside:

> Master Control Center (Agency AI System)

## Core Product Philosophy

### Current state

The current system can pull reviews and support reply workflows, but it still behaves more like an internal utility than a true operations platform.

Current gaps:

- no consistent priority system
- no business-impact framing
- weak workflow ownership
- limited visibility into risk and urgency
- limited integration posture for a larger master platform

### Target state

The platform should answer these questions immediately:

1. What needs attention now?
2. Which store is at risk?
3. Which reviews affect reputation or revenue most?
4. What action should be taken next?
5. Is the system healthy or blocked?

## Position Inside Master Control Center

Recommended long-term placement:

```text
E:\Project\Master
│
├── unified/
│   ├── connectors/
│   │   ├── review_connector.py
│   │   ├── marketing_connector.py
│   │   ├── dashboard_connector.py
│   │   └── integration_connector.py
│
├── modules/
│   ├── review-system/
│   ├── marketing-system/
│   ├── finance-system/
│
├── unified_jobs/
│   ├── job_queue.py
│   └── job_runner.py
```

### Strategic interpretation

The review system should not remain isolated forever. It should become one operational module inside a wider agency control center with:

- shared connector concepts
- shared job orchestration
- shared observability
- shared user/role identity

## Target Internal Architecture

### 1. Connector layer

Responsibilities:

- ingest Google reviews
- ingest Yelp reviews
- manage per-source session/access requirements
- expose stable source contracts to the rest of the system

### 2. Processing layer

Responsibilities:

- normalize source data
- detect reply status
- apply deduplication
- compute freshness and unreplied state
- assign priority metadata

### 3. Intelligence layer

This is the most important new layer.

Responsibilities:

- classify review type:
  - complaint
  - praise
  - neutral
- detect urgency
- tag keywords:
  - rude staff
  - slow service
  - food quality
  - wait time
  - cleanliness
- estimate business risk
- support safe AI reply generation

### 4. Action layer

Responsibilities:

- reply workflow
- assignment workflow
- escalation
- task ownership
- operator approval and final action state

### 5. Monitoring layer

Responsibilities:

- job tracking
- sync tracking
- source/session health
- error classification
- performance and trend reporting

## Dashboard Redesign

The current product should evolve into three core surfaces.

### A. Executive Dashboard

Audience:

- CEO
- owner
- leadership

Must show:

- total reviews in last 7 days
- unreplied reviews
- negative reviews (1–2 stars)
- critical reviews (negative + unreplied)
- store ranking / store risk summary

Example structure:

```text
[ TOTAL REVIEWS ] [ NEED REPLY ] [ NEGATIVE ] [ CRITICAL ]

Store A | 5 critical
Store B | 2 pending
Store C | clean
```

Goal:

Leadership should understand the state of the business in 10 seconds.

### B. Operations Inbox

This should become the main operational screen.

Replace:

> a passive list of reviews

With:

> a task-based inbox

Each item should show:

- store
- source
- rating
- short review text
- priority badge:
  - urgent
  - normal
  - low
- workflow status:
  - pending
  - in progress
  - replied
  - escalated
  - blocked

Recommended sort order:

1. negative + unreplied
2. older unreplied
3. newly ingested reviews

Primary item actions:

- open review
- generate reply
- assign to staff
- mark done

### C. Store Health View

Each store should have a health surface showing:

- review trend
- average rating
- response rate
- response time
- complaint categories
- open risk count

## Priority System

### Why it matters

Without a real priority system, the queue is just a list. The product becomes powerful only when it helps the team decide what to handle first.

### Priority formula

```text
priority_score =
    rating_weight
  + no_reply_penalty
  + age_factor
  + keyword_impact
```

### Example weights

| Condition | Score |
| --- | --- |
| 1-star | +50 |
| 2-star | +30 |
| no reply | +40 |
| older than 3 days | +20 |
| keyword “rude” | +30 |

### Suggested output bands

- Critical: 80+
- Medium: 40–79
- Low: below 40

### Product implication

Priority should not stay hidden in backend logic only. It should drive:

- queue sorting
- badges
- escalation
- alerts
- executive summary

## AI Layer

### Required capabilities

1. Sentiment analysis
   - positive
   - neutral
   - negative

2. Intent detection
   - complaint
   - refund request
   - praise
   - question

3. Smart reply generation
   - tone by rating
   - tone by brand
   - safe handling for negative reviews

### Prompt direction

The AI should act like a restaurant manager with:

- polite tone
- professional tone
- human tone

Negative pattern:

- acknowledge
- apologize carefully
- offer resolution or offline follow-up

Positive pattern:

- thank
- reinforce brand warmth
- invite guest back

## KPI System

### Operational KPIs

- response rate
- average response time
- unreplied count

### Quality KPIs

- rating trend
- sentiment trend
- complaint category trend

### Advanced business KPIs

Future correlation layer:

- reviews up vs revenue up
- reputation decline vs store issues

## Integration With Master Control Center

The review system should expose clean API surfaces such as:

```text
GET /reviews/summary
GET /reviews/inbox
POST /reviews/reply
GET /reviews/store-health
GET /reviews/kpi
```

Master Control Center should eventually be able to:

- trigger sync
- view inbox
- assign tasks
- inspect KPIs
- monitor system health

## Automation and Scheduling

### Required jobs

- daily sync
- optional hourly quick sync
- critical review alerting

### Required alerts

Trigger alerts for:

- new 1-star review
- unreplied review older than 24h
- sync failure
- session/auth blockage

## Role System

### CEO

- view everything
- no need to reply directly

### Manager

- approve replies
- monitor store performance
- track queue health

### Staff

- handle reviews
- draft replies
- execute assigned tasks

### Required permission areas

- assign reviews
- reply to reviews
- approve replies
- view analytics
- monitor source health

## UI/UX Upgrade Principles

These principles should govern future product work:

1. Inbox-first design
2. No unnecessary technical terminology
3. Important status always visible
4. One-click actions where possible
5. No hidden errors
6. Business clarity over feature density

## Migration Plan

### Phase 1

- stabilize current system
- fix QA and startup issues
- improve error visibility

### Phase 2

- build inbox-first UI
- add priority scoring
- sort by urgency

### Phase 3

- add AI intelligence layer
- add KPI surfaces
- add complaint clustering

### Phase 4

- integrate into Master Control Center
- unify jobs/connectors/identity

## What Success Looks Like

### Before

- manually check review portals
- slow response workflow
- inconsistent handling
- missed negative reviews

### After

- open system
- instantly see risk and next actions
- handle reviews in minutes
- avoid missed critical issues
- see cross-store visibility in one place

## Strategic Expansion

Future expansion path:

- multi-client agency reputation tool
- SaaS for restaurant groups
- integrations with:
  - Google Ads
  - POS systems
  - CRM
  - broader marketing control center

## Final Direction For Dev Team

This should be treated as a core operational system that affects:

- customer experience
- team response speed
- brand trust
- revenue protection

Focus on:

- clarity
- reliability
- speed
- actionability

Avoid:

- overly complex UI
- hidden logic
- engineering-heavy flows that reduce operator trust
