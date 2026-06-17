# Emerald Canopy Agent Policy

Status: draft v3.4

Emerald Canopy is a reusable agent policy for high-quality repo work, benchmark
runs, and operational TUI lanes. It should be referenced from role prompts rather
than pasted wholesale into every system prompt.

The v3.3 policy is strongest as an execution contract. This v3.4 draft keeps the
quality bar while separating local, air-gapped engineering from connected
operations, deployment, and benchmark work.

## Integration Rule

Do not make Emerald Canopy the whole identity of an agent. Keep each role prompt
focused on mission and ownership, then add a compact policy pointer:

```text
Apply the Emerald Canopy policy profile for execution quality. Use the mode
selected by the operator or repo. If no mode is selected, use air_gapped for
local repo-only work and connected for TUI, cloud, Confluence, GitHub, AWS,
Bedrock, or web-backed work. Deploy, spend, credential, public routing, and
destructive steps require explicit approval unless the operator has already
approved that exact action class.
```

## Mode Summary

- `air_gapped`: offline repo work, no network, no live installs, no external
  state changes.
- `connected`: normal TUI and devops investigation where connectors, cloud APIs,
  web search, GitHub, Confluence, or Bedrock may be required.
- `deploy`: connected mode plus stricter approval gates for public routing,
  production mutation, secrets, service restarts, spend, and irreversible work.
- `benchmark`: connected mode plus strict route selection, token-cost logging,
  repeatable artifacts, and model/result comparison.

## Conflict Resolution

1. System and developer instructions outrank this policy.
2. Explicit operator instructions outrank repo defaults.
3. Repo `AGENTS.md` and local runbooks outrank generic Emerald Canopy defaults.
4. A selected mode outranks the default mode.
5. If a rule says "forbidden" but the task clearly requires that capability, stop
   at the approval boundary and name the exact action that needs approval.

## Refined Profile

```yaml
profile: emerald_canopy
version: "3.4-draft"
purpose: "Offline-first engineering quality policy with connected-operation modes."

runtime:
  default_cap_minutes: 10
  operator_budget_may_override: true
  stop_before_guardrail_minutes: 2

paths:
  writable:
    - "$PWD"
    - "$CACHE_DIR"
    - "$LOG_DIR"

modes:
  air_gapped:
    outbound_network: forbidden
    inbound_network: forbidden
    package_installs: forbidden
    external_state_changes: forbidden
    default_for:
      - local_repo_only
      - offline_tests
      - prompt_review
  connected:
    outbound_network: task_approved
    inbound_network: forbidden
    package_installs: approval_required
    external_state_changes: approval_required
    default_for:
      - tui_ops
      - confluence
      - github
      - aws
      - bedrock
      - web_search
  deploy:
    inherits: connected
    explicit_approval_required_for:
      - public_routing
      - production_data_mutation
      - credential_rotation
      - service_restart
      - billing_or_quota_change
      - destructive_action
      - irreversible_action
  benchmark:
    inherits: connected
    route_lock_required: true
    token_cost_logging_required: true
    artifact_required: true
    compare_against_baseline: true

coverage:
  baseline: 0.70
  target: 0.95
  ratchet_per_quarter: 0.05
  measurement:
    tool: coverage.py
    report_format: xml
    per_pr: true
  enforcement:
    mode: informational
    enforce_on_branches: []
  ci_status_check:
    allowed_when_informational: true
    must_not_block_merge_until_enforced: true

tests:
  deterministic_seed_env: SEED
  unit_target_ms: 100
  smoke:
    max_minutes: 3
    python: "pytest -m 'smoke or unit'"
    node: "npm test -- --runInBand --testPathPattern='(unit|smoke)'"
    php: "phpunit --group smoke"
  full:
    max_minutes: 30
    python: "pytest"
    node: "npm test"
    php: "phpunit"
  suite_target_minutes: 10
  suite_legacy_max_minutes: 30
  slow_markers:
    - slow
    - integration
    - e2e
  full_suite_policy:
    always_on_branches:
      - staging
      - main
    force_env: FULL_SUITE
    skip_env: SKIP_FULL_SUITE
    min_remaining_minutes_for_full: 4
    allow_push_without_full:
      doc_only: true
      comment_only: true
      leaf_module_changes: true
      infra_or_cross_cutting: false

language_tooling:
  python:
    formatter: "ruff format"
    linter: "ruff check"
    type_checker: mypy
    security: bandit
    tests: pytest
  node:
    formatter: prettier
    linter: eslint
    tests: "npm test"
  php:
    linter: phpcs
    tests: phpunit
  bash:
    linter: shellcheck
  groovy:
    linter: npm-groovy-lint

agent_policy:
  step_order:
    - detect_change_scope
    - inspect_existing_contracts
    - lint_auto_fix_scoped
    - run_smoke_tests
    - run_type_and_security_checks_when_available
    - run_full_suite_if_required_or_time_allows
    - summarize_files_tests_costs_and_risks
  dirty_worktree:
    never_revert_unrelated_user_changes: true
    avoid_broad_formatting_when_unrelated_changes_exist: true
  ci_editing:
    allowed: true
    rules:
      - "Do not weaken critical status checks without explicit instruction."
      - "Prefer explicit smoke and full tiers over ad hoc filters."
  dependency_updates:
    approval_required: true
    prefer_existing_vendor_update_script: true

benchmark_policy:
  per_ticket_ledger_fields:
    - ticket_id
    - run_id
    - started_at
    - finished_at
    - runtime
    - model
    - route_lock
    - input_tokens
    - output_tokens
    - total_tokens
    - estimated_cost_usd
    - elapsed_seconds
    - outcome
    - artifact_paths
  validity_checks:
    - strict_model_route_selected
    - fresh_context_for_each_model
    - baseline_included
    - failure_reason_recorded
    - cost_basis_recorded

security:
  secrets:
    never_print: true
    approved_sources:
      - "$SECRETS_PATH"
      - aws_secrets_manager
    aws_secrets_manager_requires_mode:
      - connected
      - deploy
      - benchmark
  pii:
    plaintext_in_logs: forbidden
    storage_strategy: salted_sha256
    salt_source: "$SECRETS_PATH/pii_salt"
  supply_chain:
    image_signing: cosign
    sbom_tool: syft
    osv_scanning: osv-scanner

git:
  protected_branches:
    - staging
    - main
  branch_protection:
    required_reviews: 1
    required_status_checks: all
  commit_messages:
    ascii_default: "type(scope): summary"
    themed_prefix_optional: true
    hotfix_direct_to_main: allowed_by_repo_policy_only

final_response:
  include:
    - concrete_changes
    - commands_or_tests_run
    - artifacts
    - skipped_tests_with_reason
    - known_risks
  status_words:
    - DONE
    - BLOCKED
    - CHECKPOINT
```

## Prompt Fragment For Role Prompts

Use this compact block when a live role prompt needs the policy:

```text
Emerald Canopy execution policy:
- Use air_gapped mode for local repo-only work unless the operator or repo selects
  connected, deploy, or benchmark mode.
- Use connected mode for TUI, Confluence, GitHub, AWS, Bedrock, web-backed,
  or cross-machine work.
- Use deploy mode before production mutation, public routing, service restarts,
  credential rotation, spend, destructive actions, or irreversible actions.
- Use benchmark mode for model comparisons. Each ticket/run must log route,
  model, token use, estimated cost, elapsed time, outcome, and artifacts.
- Follow repo AGENTS.md first. Never revert unrelated user changes. List tests
  run, skipped checks, changed files, and residual risk.
```

## Recommended Rollout

1. Add the prompt fragment to repo-only Codex prompts first.
2. Add `connected` mode to Control Plane, KPI, Gold Book, NetOps, and other
   code-authoring or operations prompts instead of using strict air-gap defaults
   there.
3. Add `benchmark` mode to model-comparison and loop-canary entrypoints.
4. Keep live prompt rollout separate from this docs change so it can be reviewed
   and verified role by role.

## Current Local Template Targets

- Control Plane: code, admin, data, runbook, and benchmark lane. Default to
  `connected`; use `benchmark` for CP/KPI/Gold Book comparisons and `deploy`
  before high-impact actions.
- Diamond Roc: Evergreen site/service code and operations lane. Default to
  `connected`; allow `air_gapped` only for local repo-only edits under the
  canonical service path.
- Scout/Ranger: research collection lane only. Do not add code-authoring
  Emerald Canopy rules here; Scout should package findings and hand execution
  back to the owning lane.
