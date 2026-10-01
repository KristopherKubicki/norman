"""Behavioral checks for input bursts in both rendered console scripts."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "scripts/norman_codex_web.py",
        "scripts/agent_console_template/agent_console_web.py",
    ],
)
def test_input_burst_saves_every_draft_but_batches_auxiliary_work(path):
    source = (Path(__file__).resolve().parents[1] / path).read_text()
    start = source.index("    let composerInputFrame = 0;")
    end = source.index('    el.tmuxInput.addEventListener("keydown"', start)
    script = source[start:end].replace("{{", "{").replace("}}", "}")
    harness = """
const assert = require("node:assert/strict");
let input;
let frame;
let timerId = 0;
const timers = new Map();
const calls = {};
const drafts = [];
const count = name => () => { calls[name] = (calls[name] || 0) + 1; };
const window = {
  requestAnimationFrame(callback) { frame = callback; return 1; },
  setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
  clearTimeout(id) { timers.delete(id); }
};
const el = { promptInput: {
  value: "",
  addEventListener(event, callback) { input = callback; }
}};
const state = { snapshot: {} };
const playInteractionTone = count("tone");
const clearInterruptSubmitConfirm = count("confirm");
const autoresize = count("layout");
const updateComposerToolbar = count("toolbar");
const renderPromptSafetyRail = count("safety");
const scheduleComposerReserve = count("reserve");
const renderOperatorFocus = count("focus");
const renderSuggestions = count("suggestions");
const renderPromptCostEstimate = count("cost");
const persistPromptDraft = value => drafts.push(value);
"""
    assertions = """
for (let i = 1; i <= 20; i++) {
  el.promptInput.value = "x".repeat(i);
  input();
}
assert.equal(drafts.length, 20, "every input is saved immediately");
assert.equal(drafts.at(-1), "x".repeat(20));
assert.equal(calls.layout || 0, 0, "input dispatch must not force layout");
assert.equal(calls.cost || 0, 0, "estimates must not block input");
frame();
assert.equal(calls.layout, 1, "one layout for a burst within a frame");
assert.equal(calls.toolbar, 1);
assert.equal(calls.safety, 1);
assert.equal(timers.size, 1);
for (const callback of timers.values()) callback();
assert.equal(calls.cost, 1);
assert.equal(calls.suggestions, 1);
"""
    result = subprocess.run(
        ["node", "-e", harness + script + assertions],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
