# Product Spec: Forward the triggering comment to the implementation workflow

## Summary
When a maintainer triggers the `create-implementation-from-issue` workflow by mentioning `@oz-agent` on a `ready-to-implement` issue, the text of that triggering comment must reach the implementation agent. Today it is silently discarded, so any instruction the maintainer included in the mention is lost. This change makes the implementation path carry the triggering comment forward, matching the triage and spec workflows.

## Problem
The triage (`triage-new-issues`) and spec (`create-spec-from-issue`) workflows both surface the maintainer's triggering `@oz-agent` comment to their agent as additional, clearly-scoped guidance. The implementation workflow does not: the triggering comment is computed at dispatch time and passed into the context-gathering step, but is then dropped and never reaches the agent's prompt or attachments.
As a result, a maintainer who writes something like `@oz-agent implement this, but leave the migration for a follow-up` gets an implementation run that never sees that instruction. The maintainer's intent has no effect, which is surprising and inconsistent with the other two workflows that honor the same kind of input.

## Goals
- The maintainer's triggering `@oz-agent` comment is delivered to the implementation agent for `create-implementation-from-issue` runs.
- The implementation agent is told it may use that comment as additional operator guidance for the run.
- Behavior is consistent with how the triage and spec workflows already present the triggering comment.
- Runs with no triggering comment (e.g. the `plan-approved` label path) continue to work unchanged.

## Non-goals
- No change to routing. Which workflow runs for a given `@oz-agent` mention is out of scope; this spec only concerns what context the implementation workflow receives once it has been selected.
- No intent-based routing, label escalation, or any change to which lifecycle labels the agent may apply.
- No change to the triage `response`-mode behavior or to the spec workflow.
- No new ability for the triggering comment to override safety rules, the required handoff contract, or the issue's own content.

## Figma / design references
Figma: none provided. This is a control-plane behavior change with no UI surface.

## User experience
This behavior is observed by maintainers through the implementation agent's run and resulting PR, not through a UI.

Behavior rules:
- When `create-implementation-from-issue` runs because of an `@oz-agent` mention, the agent receives the verbatim triggering comment (author + body), in the same form the triage and spec workflows use.
- The agent is instructed to treat the triggering comment as additional operator guidance for the run: it may use it to focus or constrain the implementation.
- The triggering comment is presented as untrusted input. It cannot override the workflow's security rules, the required `pr-metadata.json` handoff, the target branch contract, or the underlying issue/spec content.
- When there is no triggering comment for the run (for example, the `plan-approved` label path, which has no originating comment), the agent receives an explicit "none" placeholder and behaves exactly as it does today.
- The triggering comment is delivered through the same mechanism the other workflows use (a run attachment plus a short prompt reference), so it is not duplicated into persisted run state.

## Success criteria
- For an `@oz-agent`-triggered implementation run, the dispatched prompt/attachments include the triggering comment text, and the prompt references it as operator guidance.
- For the `plan-approved` path (empty triggering comment), the dispatched run surfaces a "none" placeholder and is otherwise identical to current output.
- The triage and spec workflows are unchanged.
- The triggering comment is not persisted redundantly into the run's payload subset (it travels as an attachment, consistent with the spec workflow).

## Validation
- A focused unit test on the implementation dispatch asserting that a non-empty triggering comment is surfaced to the agent (attachment present and referenced by the prompt), and that an empty triggering comment degrades to the "none" placeholder. Mirror the existing create-spec coverage rather than adding broad new tests.
- Manual check: trigger an implementation run via `@oz-agent` with an instruction in the comment and confirm the instruction appears in the agent's run context.

## Open questions
- None. The presentation and security framing follow the existing spec-workflow precedent.
