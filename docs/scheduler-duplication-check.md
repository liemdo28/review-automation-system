# Scheduler Duplication Check

## Risk

Because APScheduler is started in the FastAPI lifespan, development reloads can accidentally register duplicate jobs if startup does not guard job creation.

## Change Applied

The app now:

- checks existing job IDs before adding jobs
- uses `replace_existing=True`
- starts the scheduler only when it is not already running
- shuts down only when it is running

## Result

This reduces duplicate registration risk in:

- repeated test lifespans
- local restarts
- development reload transitions

## Remaining Caveat

Hot reload still recreates processes during development. The new guard prevents duplicate jobs inside the active process, but the real production-safe behavior should still assume:

- one web process for in-process scheduling, or
- a dedicated scheduler/worker topology for scaled deployments
