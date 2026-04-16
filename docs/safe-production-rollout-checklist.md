# Safe Production Rollout Checklist

## Environment

- [ ] PostgreSQL and Redis are provisioned and reachable
- [ ] `.env` values are complete and correct
- [ ] `OPENAI_API_KEY` is configured if AI drafting is required
- [ ] SMTP credentials are configured if alerts are required
- [ ] session storage directory is writable

## Startup

- [ ] `docker-compose up -d` completes successfully
- [ ] `alembic upgrade head` succeeds on the target DB
- [ ] `python -m scripts.seed_locations` succeeds
- [ ] `start.bat` launches and leaves readable logs
- [ ] `/api/health` returns `ok`

## Review Operations

- [ ] sources appear in dashboard
- [ ] session health is visible
- [ ] fetch runs without hidden errors
- [ ] unreplied reviews appear in queue
- [ ] AI suggestions generate or degrade gracefully when unavailable
- [ ] `DRY_RUN=true` prevents posting
- [ ] live posting is enabled only intentionally

## Safety

- [ ] operators can distinguish manual approval vs browser auto reply
- [ ] failures appear in UI, not only logs
- [ ] posting attempts are logged with review/source context
- [ ] provider/session failures capture artifacts when relevant

## Recommended Go-Live Order

1. run in `DRY_RUN=true`
2. validate fetch and review queue health
3. validate reply generation
4. validate a single live post with operator supervision
5. only then enable broader live operations
