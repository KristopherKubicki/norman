Shared agent console template for the fleet-managed Codex web/tmux operators.

Source files here are the source of truth for:
- the web console UI
- the Codex launcher
- the tmux supervisor
- selected per-agent system prompt files

Deploy them with:

`python3 scripts/sync_agent_console_template.py`

The sync script copies these files into each live agent target and restarts the
relevant services.

On Hal, local deployed TUI files are root-owned. The repo ships a companion
system-level watcher/timer under `scripts/systemd/norman-agent-console-sync-local.*`
that keeps the local Hal consoles updated automatically from this repo while the
existing user-level sync continues to manage the remote fleet.
