# Provider Reliability Report

## Summary

The repository includes provider modules for:

- Google portal
- Yelp
- shared page-provider/base abstractions

## Reliability Assessment

### Strengths

- provider modules are separated from route handlers
- session resolution is centralized
- review matcher logic exists for safer UI posting
- auto-reply policy blocks unsafe posting cases

### Risks

- provider behavior remains session/browser dependent
- Google/Yelp HTML/UI changes may break selectors or parsing
- session validity is a hard dependency for successful pull/post flows
- public test coverage does not yet exercise providers end-to-end

## Current Recommendation

- keep providers isolated behind a stable contract
- continue to surface `reauth_required` and auth health clearly in UI
- capture failure artifacts/screenshots consistently
- add provider contract tests with mocked HTML or fixtures next
