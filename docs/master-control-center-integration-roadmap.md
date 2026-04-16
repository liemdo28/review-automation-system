# Master Control Center Integration Roadmap

## Purpose

Translate the product blueprint into an implementation-oriented roadmap that the dev team can execute in phases.

## Current Baseline

The repository already has:

- source/session management
- review ingestion
- reply suggestion workflow
- queue UI
- auto-reply policy foundation
- dashboard routes and API routes

This means the next step is not a rewrite. It is a repositioning and tightening of the product around operations value.

## Phase 1 — Stabilize Current Review System

### Goals

- make build/start reproducible
- stabilize provider/session flows
- improve source health visibility
- improve unreplied queue clarity
- complete QA + UAT loops

### Deliverables

- startup scripts reliable on operator machine
- basic tests and QA docs in repo
- blocking reasons readable
- queue sorted around urgent work first

## Phase 2 — Inbox-First Operations Surface

### Goals

- make review queue the center of the product
- convert review rows into operational tasks
- expose priority clearly

### Deliverables

- task-based inbox
- priority badges
- clear action ownership
- store and source context always visible
- executive summary separated from operator queue

## Phase 3 — Intelligence Layer

### Goals

- classify reviews beyond star rating
- detect urgency and complaint patterns
- make AI outputs more operational

### Deliverables

- sentiment classification
- complaint tagging
- urgency calculation
- recommended next action
- stronger AI summary in queue/detail views

## Phase 4 — KPI and Store Health

### Goals

- move from review handling to reputation monitoring
- expose health by store

### Deliverables

- store health page
- response rate KPI
- response time KPI
- rating and sentiment trends
- issue category breakdown

## Phase 5 — Master Control Center Integration

### Goals

- make review-system one operational module inside the master platform

### Deliverables

- stable summary endpoints
- inbox endpoints
- store health endpoints
- KPI endpoints
- shared job orchestration hooks
- shared connector concepts

## Recommended Technical Boundaries

### Keep inside review-system for now

- provider-specific logic
- review normalization
- reply workflow
- auto-reply policy
- review-specific UI

### Move or share later

- unified connector interfaces
- shared job runner
- cross-module monitoring
- shared auth/role model
- cross-product executive dashboard layer

## Product KPI for This Roadmap

We should consider the roadmap successful when:

- operators can clear review work faster than the manual method
- owners can detect store risk in seconds
- failures are visible without backend access
- the review module can plug into Master Control Center without major rewrite

## Final Note

This roadmap assumes the team keeps improving the current system in place.

It does not recommend rebuilding from scratch.
