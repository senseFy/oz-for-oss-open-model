# Tech Spec: Thread the triggering comment through the implementation workflow

## Problem
`create-implementation-from-issue` receives the maintainer's triggering `@oz-agent` comment at dispatch time but discards it before building the agent prompt, so the implementation agent never sees it. The triage and spec workflows already thread the same value through to their agents. We want the implementation workflow to forward the triggering comment the same way, with the same untrusted-input framing.

## Relevant code
- `core/workflows/create_implementation_from_issue.py:176` — `gather_create_implementation_context` accepts `triggering_comment_text` but never stores it on the returned `CreateImplementationContext`.
- `core/workflows/create_implementation_from_issue.py:136-166` — `CreateImplementationContext` TypedDict; has no triggering-comment field.
- `core/workflows/create_implementation_from_issue.py:52-55` — `_CREATE_IMPLEMENTATION_ATTACHMENT_PAYLOAD_FIELDS` (fields stripped from the persisted payload subset because they travel as attachments).
- `core/workflows/create_implementation_from_issue.py:62-119` — `build_create_implementation_prompt`; the `Fetching Issue Content` block (95-99) currently states the triggering comment is not inlined.
- `core/workflows/create_implementation_from_issue.py:122-126` — `create_implementation_context_attachments`; only emits `spec_context.md`.
- `core/workflows/create_implementation_from_issue.py:314-340` — `build_create_implementation_prompt_for_dispatch`.
- `core/workflows/create_spec_from_issue.py:56-62, 112-188, 215, 323, 352` — reference implementation: the spec workflow's `triggering_comment.md` constant, payload-subset field, prompt section, context field, and prompt wiring. Mirror this.
- `core/workflows/__init__.py:767` — `CreateImplementationWorkflow.build_dispatch` passes `triggering_comment_text=triggering_comment_prompt_text(dict(payload))`.
- `core/workflows/__init__.py:843` — `PlanApprovedWorkflow.build_dispatch` passes `triggering_comment_text=""` (no originating comment).
- `oz/helpers.py:199` — `triggering_comment_prompt_text` formats the payload comment as `@{author} commented:\n{body}` (or `""`).

## Current state
The dispatch layer already computes the triggering comment and hands it to `gather_create_implementation_context`. The gather function builds `CreateImplementationContext` from issue/spec data only; the `triggering_comment_text` argument is unused. `build_create_implementation_prompt` deliberately keeps issue content out of the prompt and points the agent at `fetch_github_context.py`, and its security note explicitly lists the triggering comment as not inlined. Attachments are limited to `spec_context.md`. Net effect: the value is dropped.
The spec workflow is the model to follow. It defines `_TRIGGERING_COMMENT_ATTACHMENT = "triggering_comment.md"`, includes `triggering_comment_text` in its attachment-payload-fields set, stores it on its context, emits it as an attachment (with a `- None` fallback), and references it in the prompt as additional context bounded by security rules.

## Proposed changes
Mirror the spec workflow precedent in `create_implementation_from_issue.py`:
1. Add a module constant `_TRIGGERING_COMMENT_ATTACHMENT = "triggering_comment.md"`.
2. Add `triggering_comment_text` to `_CREATE_IMPLEMENTATION_ATTACHMENT_PAYLOAD_FIELDS` so it is stripped from the persisted payload subset and travels only as an attachment.
3. Add `triggering_comment_text: str` to `CreateImplementationContext`.
4. In `gather_create_implementation_context`, store the received `triggering_comment_text` (normalized via `str(... or "")`) on the returned context.
5. In `create_implementation_context_attachments`, emit a `triggering_comment.md` attachment, defaulting to `- None` when empty (matching `create_spec_context_attachments`).
6. In `build_create_implementation_prompt` / `build_create_implementation_prompt_for_dispatch`, add a reference to the `triggering_comment.md` attachment and a short instruction to treat it as additional operator guidance that cannot override the security rules or the handoff contract. Update the existing `Fetching Issue Content` note (95-99) so it no longer claims the triggering comment is excluded; the issue body/comments stay behind the fetch script as today, only the triggering comment is surfaced inline.

No change to `core/workflows/__init__.py` is required: `CreateImplementationWorkflow` already passes the real comment and `PlanApprovedWorkflow` already passes `""`, which now flows through to the `- None` attachment fallback.

## End-to-end flow
1. `@oz-agent` mention on a `ready-to-implement` issue routes to `create-implementation-from-issue`.
2. `CreateImplementationWorkflow.build_dispatch` computes `triggering_comment_prompt_text(payload)` and calls `gather_create_implementation_context`.
3. The gather step now records `triggering_comment_text` on the context.
4. `build_create_implementation_prompt_for_dispatch` references `triggering_comment.md`; `create_implementation_context_attachments` emits it.
5. The agent run receives the attachment and the prompt instruction, and may use the comment as scoped guidance.
6. For the `plan-approved` path, `triggering_comment_text` is `""`, so the attachment renders `- None` and the prompt reference is inert — unchanged behavior.

## Risks and mitigations
- Prompt-injection surface: the triggering comment is attacker-influenceable. Mitigation: present it as untrusted, using the same framing as the spec workflow's security rules; it cannot override the handoff contract, branch rules, or issue/spec content.
- Inconsistency with the existing "fetch issue content via script" design: only the triggering comment is inlined; issue body/comments remain behind the fetch script, so the trusted-fetch posture for those is preserved. Update the prompt note to keep it accurate.
- Payload-subset bloat / double-carry: adding the field to `_CREATE_IMPLEMENTATION_ATTACHMENT_PAYLOAD_FIELDS` ensures it is not persisted into run state alongside the attachment.

## Testing and validation
- Add one focused test (mirroring the create-spec dispatch coverage) asserting: a non-empty triggering comment produces a `triggering_comment.md` attachment and a prompt reference; an empty triggering comment yields the `- None` fallback. Keep it scoped to this behavior rather than re-testing the whole dispatch path.
- Run the existing implementation-workflow and builder tests to confirm no regression in payload-subset shape or prompt assembly.

## Follow-ups
- None required for this change. The separate question of whether `@oz-agent` mentions should escalate not-yet-ready issues remains explicitly out of scope.
