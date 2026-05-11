# Issue #447: Add `auto-implement` label that skips triage and opens a draft PR

## Tech Spec

### Problem

The webhook router currently sends every non-bot plain `issues.opened` event to `triage-new-issues`, regardless of existing labels. It also drops bot-authored opened issues before any workflow dispatch. Issue #447 requires a narrow routing exception: if a newly opened plain issue already carries `auto-implement`, route directly to `create-implementation-from-issue`, including for bot-authored issues, and do not route to triage.

The implementation should not add a workflow. The existing `create-implementation-from-issue` workflow already gathers issue context, best-effort assigns `oz-agent`, creates or updates the progress comment, exposes session links through cron polling, consumes `pr-metadata.json`, and opens or updates a draft PR.

### Relevant code

- `core/routing.py:1` — module docstring documenting webhook routing behavior.
- `core/routing.py:83` — workflow identifier constants, including `WORKFLOW_TRIAGE_NEW_ISSUES` and `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE`.
- `core/routing.py:94` — issue lifecycle label constants for `ready-to-spec` and `ready-to-implement`.
- `core/routing.py (124-136)` — `_label_names()`, which normalizes label objects from webhook payloads.
- `core/routing.py (147-164)` — `_is_bot()`, which currently powers the bot-author drop.
- `core/routing.py (254-342)` — `_route_issues()`, the target for the routing change.
- `core/builders.py (94-103)` — `build_create_implementation_request()`, which delegates implementation dispatch to the existing workflow.
- `core/workflows/__init__.py (577-632)` — `CreateImplementationWorkflow`, which builds the dispatch request and progress-comment spec.
- `core/workflows/create_implementation_from_issue.py (143-286)` — `gather_create_implementation_context()`, which assigns `oz-agent` if missing, resolves spec context when present, and prepares progress-comment state.
- `core/workflows/create_implementation_from_issue.py (287-326)` — implementation prompt construction for the cloud run.
- `core/workflows/create_implementation_from_issue.py (329-470)` — result application that opens or updates draft implementation PRs and updates the issue progress comment.
- `tests/test_routing.py (45-126)` — current `issues.opened` and bot-author routing tests.
- `tests/test_routing.py (232-274)` — current issue-label routing tests, including unhandled-label drops.

### Current state

`_route_issues()` handles plain issue events in this order:

1. Reject missing issue payloads.
2. Drop pull requests delivered through the `issues` event.
3. For `action == "opened"`:
   - drop if `_is_bot(issue["user"])` is true.
   - otherwise return `WORKFLOW_TRIAGE_NEW_ISSUES`.
4. For `assigned`, dispatch spec or implementation only when the added assignee is `oz-agent` and the issue has the matching lifecycle label.
5. For `labeled`, dispatch spec or implementation only for `ready-to-spec` or `ready-to-implement` with an existing `oz-agent` assignee; otherwise announce availability or drop unhandled labels.

This means a trusted `auto-implement` issue currently either routes to triage or is dropped if the author is a bot. The existing implementation workflow does not require a preexisting `oz-agent` assignee because `gather_create_implementation_context()` best-effort adds the assignee when it is missing.

### Proposed changes

#### 1. Add an `auto-implement` label constant

Add a new constant in `core/routing.py` near the other label constants:

- `AUTO_IMPLEMENT_LABEL = "auto-implement"`

Export it from `__all__` for consistency with the existing lifecycle label constants. Tests do not need to import it, but exporting keeps the routing module's public surface complete.

#### 2. Update the module docstring

Update the `issues` section of `core/routing.py` to document that:

- `issues.opened` with `auto-implement` routes directly to `create-implementation-from-issue`.
- This route bypasses the normal bot-author drop.
- `issues.labeled` with `auto-implement` is intentionally not a trigger.

Keep the docstring clear that normal opened issues still route to triage.

#### 3. Route `issues.opened` with `auto-implement` before the bot-author drop

Change only the `action == "opened"` branch in `_route_issues()`:

1. Normalize labels with `_label_names(issue.get("labels"))`.
2. If `AUTO_IMPLEMENT_LABEL` is present, return `RouteDecision(WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE, "...")`.
3. Only after that, apply the existing `_is_bot(issue.get("user"))` drop.
4. Otherwise keep returning `WORKFLOW_TRIAGE_NEW_ISSUES`.

The pull-request mirror guard should remain before this branch so a PR delivered as an `issues.opened` payload is still ignored.

The decision reason should make logs distinguish this path from the existing `ready-to-implement` route, for example `auto-implement label on newly opened issue`.

#### 4. Leave `issues.labeled` behavior unchanged except for tests

Do not add `AUTO_IMPLEMENT_LABEL` to the set of routed lifecycle labels in the `action == "labeled"` branch. The existing unhandled-label path should handle it and return `workflow=None`.

This preserves the non-goal that applying `auto-implement` after issue creation is a no-op.

#### 5. Do not change implementation workflow internals

No changes are required in `core/builders.py`, `core/workflows/__init__.py`, `core/workflows/create_implementation_from_issue.py`, or cron handlers. Routing to `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE` is enough for the builder registry to reuse the current dispatch path.

The implementation prompt will receive issue labels and assignees as gathered from GitHub at dispatch time. If no approved spec or repository spec exists, the existing prompt explicitly tells the implementation agent that no approved or repository spec context was found, which is acceptable for the `auto-implement` bypass.

### End-to-end flow

#### Flow A: human-authored auto-implement issue

1. GitHub sends `issues.opened`.
2. `route_event("issues", payload)` calls `_route_issues()`.
3. `_route_issues()` rejects PR mirrors, reads issue labels, finds `auto-implement`, and returns `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE`.
4. The webhook handler evaluates the route with the existing builder registry.
5. `CreateImplementationWorkflow.build_dispatch()` gathers implementation context and creates a progress-comment spec.
6. The dispatcher starts the cloud run and stores run state.
7. Cron polling updates the session link and applies the completed implementation artifact by opening or updating a draft PR.

#### Flow B: bot-authored auto-implement issue

1. GitHub sends `issues.opened` for an issue authored by a bot account.
2. `_route_issues()` checks labels before `_is_bot(issue["user"])`.
3. Because `auto-implement` is present, routing returns `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE`.
4. The normal implementation dispatch and completion flow runs.

#### Flow C: issue without auto-implement

1. GitHub sends `issues.opened`.
2. `_route_issues()` does not find `auto-implement`.
3. Existing behavior continues:
   - bot-authored issues are dropped.
   - non-bot issues route to `triage-new-issues`.

#### Flow D: auto-implement added later

1. GitHub sends `issues.labeled` with `label.name == "auto-implement"`.
2. `_route_issues()` enters the existing labeled branch.
3. Because the label is not `ready-to-spec` or `ready-to-implement`, routing returns `workflow=None` with the unhandled-label reason.
4. No implementation run starts.

### Risks and mitigations

**Risk: trusted bot bypass unintentionally applies to all bot-authored issues.**
Mitigation: place the bypass behind the explicit `auto-implement` label check only. Bot-authored issues without the label continue to be dropped.

**Risk: adding the label later unexpectedly starts implementation.**
Mitigation: do not route `AUTO_IMPLEMENT_LABEL` in the `issues.labeled` branch. Add a regression test for this exact event.

**Risk: implementation runs without spec context.**
Mitigation: this is intentional for `auto-implement`. The existing implementation workflow already supports the no-spec-context case when no unapproved spec PR blocks execution, and the agent fetches the issue body and comments as implementation input.

**Risk: accidental triage and implementation double dispatch on issue creation.**
Mitigation: return a single `RouteDecision` from `_route_issues()` for `issues.opened`. The auto-implement branch should return before the triage branch.

**Risk: label name case or whitespace variations.**
Mitigation: `_label_names()` already strips whitespace but does not lower-case label names. Keep exact matching to align with existing label constants and GitHub label conventions.

### Testing and validation

Add unit tests in `tests/test_routing.py` under `IssuesEventTest`:

- `test_issues_opened_with_auto_implement_routes_to_create_implementation`
  - Payload: `action="opened"`, issue labels include `auto-implement`, normal user.
  - Expected: `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE`.
- `test_issues_opened_with_auto_implement_from_bot_routes_to_create_implementation`
  - Payload: `action="opened"`, issue labels include `auto-implement`, issue user is a bot.
  - Expected: `WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE`.
- Preserve or update existing tests that prove `issues.opened` without `auto-implement` routes to triage for normal users and drops bot authors.
- `test_auto_implement_label_added_to_existing_issue_is_dropped`
  - Payload: `action="labeled"`, `label.name="auto-implement"`, issue labels include `auto-implement`.
  - Expected: `workflow is None` and reason contains `unhandled label`.

Run:

- `python -m unittest tests.test_routing`
- The broader repository test command used by CI, if available in the environment.

### Follow-ups

- Operators should create and document the `auto-implement` label in repositories that opt into this behavior.
- If maintainers later want promotion-after-open semantics, that should be a separate product decision because it changes the trust and dispatch model for `issues.labeled`.
