# Kernel-Primary Pilot Proof

Status: implementation support document

## Purpose

This is a bounded proof plan for a **selected** kernel-primary TUI canary. It is
not an instruction to enable a new TUI, change environment flags, deploy a
release, or retrieve credentials. Keep `codex_direct` as the rollback path.

The accompanying offline evaluator is:

```text
scripts/kernel_primary_pilot_proof.py
```

It reads an already-exported Console Runtime event payload and produces a
pass/fail report. It makes no network requests and changes no runtime state.

## Preconditions

Before an operator runs the pilot, confirm all of the following through the
normal release process:

- The chosen canary is deliberately configured for the `kernel` backend with
  kernel execution and kernel-primary enabled.
- The work is read-only, safe to repeat, and contains no secrets or personal
  data.
- The operator can collect the resulting events from the authenticated Console
  Runtime API; do not add credentials to command lines, reports, or source
  control.
- Cloud fallback behavior is understood and visible. A fallback is not proof of
  local kernel execution.
- `codex_direct` rollback is available and tested for that TUI.

## Five Safe Pilot Cases

Tag each associated job or event metadata with `pilot_case` using one of these
values. The evaluator deliberately ignores prompt text and relies on this tag.

| Tag | Safe Exercise | Required Evidence |
| --- | --- | --- |
| `planner` | Plan a read-only repository or log-review task. | Local observed-worker proof, passing receipt audit and completion gate. |
| `tool_loop` | Inspect named files with a read-only tool, then summarize. | A non-model `tool.completed` event followed by model completion. |
| `parallel` | Delegate two independent read-only inspections, then merge findings. | `workstream.created` and a delegation event with at least two subtasks. |
| `verifier` | Draft a bounded answer and verify it against supplied evidence. | `verification.completed` plus a passing completion gate. |
| `degraded` | Deliberately use an approved unavailable preferred lane and complete a safe summary. | Local route proof and a visible fallback/degraded indication. |

Do not use destructive commands, external writes, deployment actions, or
credentialed tools for these cases.

## Export And Evaluate

After the operator has completed the five cases, export just the related
Console Runtime events via the normal authenticated operator workflow. Save the
response as JSON (an `events` or `items` array) or JSONL.

Run the evaluator locally against that exported artifact:

```bash
python3 scripts/kernel_primary_pilot_proof.py pilot-events.json \
  --output-json /tmp/kernel-primary-pilot-proof.json \
  --output-md /tmp/kernel-primary-pilot-proof.md
```

Exit status `0` means all five cases are proven by the export. Exit status `1`
means the export is valid but one or more evidence requirements are missing.
Exit status `2` means the export could not be parsed.

## Interpretation

A passing report proves only the specific five exported cases. It does not
justify a fleet-wide rollout. Expand only after reviewing the evidence,
operator experience, latency, and fallback rate. A failed report is useful: it
names the missing evidence rather than silently treating a model response as a
completed kernel workflow.

## Rollback

If the canary is degraded or the proof cannot be completed, return the selected
TUI to its previously tested `codex_direct` configuration through the standard
release workflow. Preserve the event export and proof report for diagnosis.
