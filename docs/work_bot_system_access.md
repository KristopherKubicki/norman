# Work Bot System Access

Date: 2026-04-04

This is the Norman-side index for the shared OpenBrand system-access guidance
used by the work bots exposed through the public Norman bot hosts.

## Public Bot Hosts

| Hostname | Bot | Repo | Primary Prompt |
| --- | --- | --- | --- |
| `cp.work.example.test` | `control-plane` | `/home/operator/code/control_plane` | `/home/operator/code/norman/scripts/agent_console_template/prompts/control-plane.txt` |
| `goldbook.work.example.test` | `gold-book` | `/home/operator/code/gold_book` | `/home/operator/code/norman/scripts/agent_console_template/prompts/gold-book.txt` |
| `mc.work.example.test` | `mc` / Monte Carlo | `/home/operator/code/market-sizing` or successor repo | Survey, demographic, market-modeling, and Monte Carlo lane |
| `platinum.work.example.test` | `platinum-standard` | `/home/operator/code/platinum_standard` | `/home/operator/code/norman/scripts/agent_console_template/prompts/platinum-standard.txt` |

## Shared Access Guide

All three bots should use:

- `/home/operator/code/control_plane/docs/control_plane_agent_system_access.md`

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
| GAPI admin | `GAPI_SESSION_COOKIE` plus `/home/operator/code/control_plane/connectors/gapi_admin_import.py` |
| GAPI DB | AWS profile `ob-openbrand-admin` plus Secrets Manager / SSM |
| WebGOAT | `~/.webgoat.cookies.txt` in Netscape format |
| Gold Book live Sheets | Google service account configured per `/home/operator/code/gold_book/AUTH.md` |

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

## Research Routing

Scout/Ranger is the work research collection lane only.

Use Scout for:

- external research and source discovery
- Perplexity/watchlist/datastream work
- evidence collection and contradiction checks
- market/source context packets
- research packet prep for another owning lane

Do not send Scout:

- implementation work
- deploys, restarts, or service mutation
- credentials, root access, or auth bundle inspection
- final admin/data execution decisions

The owning lane keeps final execution. Control Plane owns admin/data execution;
Gold Book, Platinum Standard, and the other work lanes own their own
build/release mutations. Scout should return structured findings, source notes,
and open questions back through Norman/Switchboard or the owning lane.

## Ownership / Routing

| Bot | Primary Ownership | Hand Off To |
| --- | --- | --- |
| `control-plane` | GAPI admin, GAPI DB, WebGOAT, QuickSight dataset/build surfaces, Armitage evidence/runbooks, shared cleanup pipelines | Scout for research collection only; Gold Book for live SpecMasters; Platinum Standard for workbook/release builds |
| `gold-book` | Gold Book generation, getspecs, writespecs, GTIN repair, live Google Sheet SpecMasters | Scout for research collection only; Control Plane for shared access patterns; Platinum Standard for Platinum release questions |
| `platinum-standard` | Platinum workbook/release work, mirror-dependent builds, source-registry governance | Scout for research collection only; Control Plane for shared access patterns; Gold Book for live SpecMaster questions |
| `mc` | Monte Carlo, survey, demographic, and market-modeling analysis | Control Plane for shared access/auth patterns, Scout for research collection |

## Retired Lanes

- `acast` / `acast.work.example.test` is retired from the active fleet. Do not rely on it for new work unless it is explicitly re-owned and rebuilt.

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
python3 /home/operator/code/control_plane/connectors/gapi_admin_import.py --help

# GAPI DB auth check
aws sts get-caller-identity --profile ob-openbrand-admin

# WebGOAT auth check
python3 /home/operator/code/control_plane/scripts/webgoat_oneoff_probe.py --help

# Gold Book auth / writespecs
python3 /home/operator/code/gold_book/scripts/preflight.py
python3 /home/operator/code/gold_book/writespecs/cli.py --help

# Platinum Standard pipeline surface
python3 /home/operator/code/platinum_standard/scripts/v38_pipeline.py --help
```
