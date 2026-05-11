# Issue #447: Add `auto-implement` label that skips triage and opens a draft PR

## Product Spec

### Summary

Maintainers need a one-step way to send trusted, implementation-ready issues directly to the implementation agent. When a newly opened issue already has the `auto-implement` label, Oz should skip the normal triage and spec stages, dispatch the existing implementation workflow, share the run session in the progress comment, and let the existing completion path open or update a draft implementation PR.

This behavior is limited to labels present at issue creation time. Adding `auto-implement` to an existing issue after it has been opened should not start work.

### Problem

Every new issue currently goes through the `triage-new-issues` route. That is useful for normal public intake, but it slows down trusted intake pipelines where maintainers or authorized bots already know the issue is valid, scoped, and ready for implementation. Those pipelines must wait for triage and then move the issue through `ready-to-spec` or `ready-to-implement` with `oz-agent` assignment before the implementation agent starts.

The desired label lets trusted labelers express that decision at the moment the issue is created, without introducing a new workflow or duplicating implementation behavior.

### Goals

- Honor `auto-implement` when it is already present on a plain issue in the `issues.opened` webhook payload.
- Skip `triage-new-issues` for those newly opened issues so no triage progress comment or triage result is posted.
- Dispatch the existing `create-implementation-from-issue` workflow directly.
- Preserve the existing implementation workflow behavior for assignment, progress comments, session link updates, draft PR creation, and PR-link reporting.
- Treat the label itself as the authorization gate; do not require the issue to already be assigned to `oz-agent`.
- Honor the label even when the issue author is a bot account, because authorized intake bots may file and label issues in one step.
- Keep all existing routing unchanged for issues that do not have `auto-implement` at creation time.

### Non-goals

- Adding a new implementation workflow.
- Changing how `create-implementation-from-issue` builds prompts, creates progress comments, uploads artifacts, or opens draft PRs.
- Creating or managing the GitHub `auto-implement` label automatically.
- Dispatching implementation when `auto-implement` is added to an already-open issue.
- Changing `ready-to-spec`, `ready-to-implement`, `plan-approved`, or `@oz-agent` mention behavior.
- Skipping GitHub webhook signature verification, repository installation checks, or any existing dispatch preflight outside routing.

### Figma / design references

Figma: none provided. This is a GitHub automation behavior with no product UI beyond labels, issue comments, Oz session links, and draft pull requests.

### User experience

#### Scenario: trusted maintainer opens a labeled issue

1. A maintainer opens a new plain issue with `auto-implement` already applied.
2. The webhook router receives `issues.opened`.
3. Oz does not dispatch `triage-new-issues`.
4. Oz dispatches `create-implementation-from-issue`.
5. The existing implementation flow posts or updates its progress comment on the issue.
6. As the cloud agent runs, the existing poller updates the progress comment with the session link.
7. When the agent produces changes, the existing implementation completion path opens or updates a draft PR.
8. The issue progress comment includes the PR link when the workflow completes.

#### Scenario: trusted intake bot opens a labeled issue

1. An authorized bot account opens a new issue with `auto-implement` already applied.
2. Even though normal issue-opened routing ignores bot-authored issues, this event is accepted because the trusted label is present.
3. Oz dispatches `create-implementation-from-issue` with the same behavior as a maintainer-authored labeled issue.

#### Scenario: normal issue opens without the label

1. A new plain issue is opened without `auto-implement`.
2. Existing routing behavior is unchanged.
3. Non-bot-authored issues continue to route to `triage-new-issues`.
4. Bot-authored issues without the label continue to be dropped by the automation-author guard.

#### Scenario: label is added after issue creation

1. An issue is already open.
2. A maintainer or bot adds `auto-implement`.
3. The `issues.labeled` event is not treated as an implementation trigger.
4. Oz logs and drops the label event the same way it drops other unhandled issue labels.
5. Maintainers can still use existing promotion paths such as `ready-to-implement` plus `oz-agent` assignment or an `@oz-agent` mention on an issue that is already ready to implement.

#### Behavior rules

1. **Only `issues.opened` can use `auto-implement`.** The label is read from the issue's labels at creation time.
2. **Plain issues only.** Pull requests mirrored through the `issues` event remain ignored by the issue router.
3. **The label bypasses the bot-author drop.** Bot-authored issues are still dropped by default, but not when `auto-implement` is present on `issues.opened`.
4. **The label bypasses `oz-agent` assignment requirements.** The implementation workflow can perform its existing best-effort assignment behavior.
5. **No triage side effects occur for the bypass path.** A newly opened issue with `auto-implement` should not receive a triage comment, triage labels, or triage recommendations from this event.
6. **Existing lifecycle labels keep their current meaning.** `ready-to-spec` and `ready-to-implement` do not become aliases for `auto-implement` on issue creation.
7. **Unhandled label events remain safe no-ops.** `issues.labeled` for `auto-implement` should produce no workflow dispatch.

### Success criteria

1. A newly opened plain issue with `auto-implement` routes to `create-implementation-from-issue`.
2. A newly opened plain issue with `auto-implement` does not route to `triage-new-issues`.
3. A newly opened plain issue with `auto-implement` authored by a bot account still routes to `create-implementation-from-issue`.
4. A newly opened issue without `auto-implement` preserves existing behavior, including triage for normal users and no dispatch for bot-authored issues.
5. Adding `auto-implement` through an `issues.labeled` event does not dispatch any workflow.
6. Existing `ready-to-spec` and `ready-to-implement` routing tests continue to pass unchanged.
7. The implementation flow still surfaces the session link and PR link through the existing progress-comment and poller behavior.

### Validation

- Add unit tests in `tests/test_routing.py` for:
  - `issues.opened` with `auto-implement` routing to `create-implementation-from-issue`.
  - `issues.opened` with `auto-implement` from a bot author still routing to `create-implementation-from-issue`.
  - `issues.opened` without `auto-implement` preserving existing triage and bot-drop behavior.
  - `issues.labeled` with `auto-implement` returning no workflow and a dropped/unhandled-label reason.
- Run the routing test module after implementation.
- Run the repository test suite or the closest available CI-equivalent command when practical.
- Inspect `core/routing.py` documentation to confirm the new label is described alongside existing issue routes.

### Open questions

None. The issue defines the trust boundary, scope, and desired routing behavior clearly.
