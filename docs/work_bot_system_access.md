# Work Bot System Access

Date: 2026-04-04

This is the Norman-side index for the shared OpenBrand system-access guidance
used by the work bots exposed through the public Norman bot hosts.

## Public Bot Hosts

| Hostname | Bot | Repo | Primary Prompt |
| --- | --- | --- | --- |
| `cp.[REDACTED_NAME].openbrand.com` | `control-plane` | `/home/[REDACTED_NAME]/code/control_plane` | `/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/prompts/control-plane.txt` |
| `goldbook.[REDACTED_NAME].openbrand.com` | `gold-book` | `/home/[REDACTED_NAME]/code/gold_book` | `/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/prompts/gold-book.txt` |
| `platinum.[REDACTED_NAME].openbrand.com` | `platinum-standard` | `/home/[REDACTED_NAME]/code/platinum_standard` | `/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/prompts/platinum-standard.txt` |

## Shared Access Guide

All active work bots here should use:

- `/home/[REDACTED_NAME]/code/control_plane/docs/control_plane_agent_system_access.md`

That guide covers the common shared surfaces:

- GAPI admin
- GAPI database
- WebGOAT / Scrapegoat
- QuickSight
- Armitage

The key operating rule is:

- do not say a system is inaccessible until the expected auth artifact is
  checked
- prefer repo helper scripts and connectors over inventing a new access path

## Expected Auth Artifacts

| Surface | Expected Access Artifact / Pattern |
| --- | --- |
| GAPI admin | `GAPI_SESSION_COOKIE` plus `/home/[REDACTED_NAME]/code/control_plane/connectors/gapi_admin_import.py` |
| GAPI DB | AWS profile `ob-openbrand-admin` plus Secrets Manager / SSM |
| WebGOAT | `~/.webgoat.cookies.txt` in Netscape format |
| Gold Book live Sheets | Google service account configured per `/home/[REDACTED_NAME]/code/gold_book/AUTH.md` |

## Failure Language

The bots should report the missing dependency explicitly:

- missing `GAPI_SESSION_COOKIE`
- missing `~/.webgoat.cookies.txt`
- missing AWS profile `ob-openbrand-admin`
- missing Google service-account credentials
- missing Armitage run URL / ticket / source evidence

They should not say:

- "I don't know how to access GAPI"
- "I don't know how to access WebGOAT"
- "I don't know how to access QuickSight"

## First 5 Minutes

Every work bot should do the same startup pass before claiming it is blocked:

1. Check repo state with `git status --short`.
2. Read the dated handoff / operator brief for its repo.
3. Check auth artifacts relevant to the task.
4. Check local service health.
5. Summarize what is present, what is missing, and what is blocked.

## Ownership / Routing

| Bot | Primary Ownership | Hand Off To |
| --- | --- | --- |
| `control-plane` | GAPI admin, GAPI DB, WebGOAT, QuickSight dataset/build surfaces, Armitage evidence/runbooks, shared cleanup pipelines | Gold Book for live SpecMasters, Platinum Standard for workbook/release builds |
| `gold-book` | Gold Book generation, getspecs, writespecs, GTIN repair, live Google Sheet SpecMasters | Control Plane for shared access patterns, Platinum Standard for Platinum release questions |
| `platinum-standard` | Platinum workbook/release work, mirror-dependent builds, source-registry governance | Control Plane for shared access patterns, Gold Book for live SpecMaster questions |

## Known Blockers

- Missing `GAPI_SESSION_COOKIE`
- Missing `~/.webgoat.cookies.txt`
- Missing AWS profile `ob-openbrand-admin`
- Missing Google service-account credentials
- Sheet permission block on the target workbook
- QuickSight UI request without the dataset/build artifact
- Armitage request without the run URL, ticket, or evidence pack
- Platinum mirror absent under `/data/platinum_standard/...`

## Common Task Snippets

```bash
# GAPI admin
python3 /home/[REDACTED_NAME]/code/control_plane/connectors/gapi_admin_import.py --help

# GAPI DB auth check
aws sts get-caller-identity --profile ob-openbrand-admin

# WebGOAT auth check
python3 /home/[REDACTED_NAME]/code/control_plane/scripts/webgoat_oneoff_probe.py --help

# Gold Book auth / writespecs
python3 /home/[REDACTED_NAME]/code/gold_book/scripts/preflight.py
python3 /home/[REDACTED_NAME]/code/gold_book/writespecs/cli.py --help

# Platinum Standard pipeline surface
python3 /home/[REDACTED_NAME]/code/platinum_standard/scripts/v38_pipeline.py --help
```
