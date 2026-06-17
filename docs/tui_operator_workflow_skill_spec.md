# TUI Operator Workflow Skill Spec

This spec captures common TUI workflows that were previously implicit in UI code,
old sessions, and operator habit. They should be benchmarked like runbooks because
they happen across every TUI and they affect cost, safety, and operator trust.

The baseline policy is Bedrock-first for work-special TUIs. Personal TUIs may draft
or summarize, but OpenBrand work execution stays on work-special surfaces with an
explicit tenant, purse, and authority label.

## Workflow Matrix

| Workflow | Skill ID | Default Model Shape | Validator / Gate |
| --- | --- | --- | --- |
| Local watch/status inventory | `local_status_inventory` | Local deterministic only | `/api/status`, queue depth, BBS summary |
| Operator status answer | `tui_operator_status_answer` | Cheap Bedrock worker after local snapshot | Must not start new work or invent missing state |
| Working-on recap and plan estimate | `tui_working_on_plan_estimate` | Cheap Bedrock worker for advisory estimate | Log initial, planned, and final cost/skill/tool estimates |
| Queue, interrupt, staged prompt recovery | `tui_queue_interrupt_recovery` | Cheap Bedrock worker can recommend wait/remove/interrupt | Queue depth before/after and explicit UI action |
| Safe undo/unwind gate | `tui_safe_undo_or_unwind_gate` | Bedrock GPT-5.4 xhigh gate | Latest-turn boundary, external-write boundary, rollback checklist |
| BBS close-loop decision | `tui_bbs_close_loop_decision` | Bedrock GPT-5.4 xhigh gate before write | Owner/observer role, ACK semantics, concrete DONE/BLOCKED reason |
| Tenant, purse, and route policy check | `tui_tenant_purse_route_check` | Bedrock GPT-5.4 xhigh gate | Work-special vs personal, billing owner, route default approval |
| Context resume and handoff digest | `tui_context_resume_handoff` | Cheap Bedrock worker after targeted retrieval | Redaction, tenant label, stale-memory warning |
| Session-to-runbook promotion | `tui_session_to_runbook_promotion` | Cheap extraction plus Bedrock GPT-5.4 review | Redaction, deterministic validator, benchmark case manifest |

## Model Rules

- Use no model for pure status polling, inventory checks, queue depth reads, and
  unchanged-ticket/watch loops.
- Use cheap Bedrock workers for bounded narration, extraction, simple retrieval,
  plan estimates, queue advice, and context handoff drafts.
- Use Bedrock GPT-5.4 xhigh when the workflow interprets authority, rollback,
  tenant/purse routing, BBS lifecycle writes, or session-to-runbook promotion.
- Reserve Bedrock GPT-5.5 xhigh for rare high-authority final decisions, not for
  ordinary operator status or worker tasks.

## Logging Contract

Each nontrivial TUI turn should eventually log:

| Field | Meaning |
| --- | --- |
| `operator_intent` | The normalized task as the planner understood it |
| `planned_workflow_skill_ids` | Named workflow/runbook/skill IDs expected to be used |
| `estimated_tool_count` | Expected distinct tool families |
| `estimated_skill_count` | Expected skill/runbook count |
| `estimated_model_lanes` | Local, cheap worker, 5.4 gate, 5.5 final |
| `estimated_cost_usd` | Rate-card estimate, marked non-invoice-reconciled |
| `final_tool_count` | Actual tool families used |
| `final_skill_count` | Actual skill/runbook count used |
| `final_cost_usd` | Actual or observed estimate |
| `estimate_delta_notes` | Why planned vs final differed |

## Benchmark Hooks

The canonical benchmark entries are in `scripts/gaphelp_ticket_loop_shadow.py`:

- `control_plane_threshold_matrix` includes operator status, queue/interruption,
  and undo/unwind as issue classes.
- `foundational_skill_matrix` includes the common TUI workflow primitives.
- `tui_operator_workflow_matrix` is the dedicated view for the common TUI skills.

The session miner in `scripts/work_session_runbook_miner.py` also recognizes
`tui_operator_common_workflows` so old sessions can promote repeatable behavior into
runbooks, skills, tools, and benchmark cases.
