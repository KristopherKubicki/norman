from app.core.command_policy import evaluate_tmux_payload


def test_tmux_chat_allows_plain_text():
    decision = evaluate_tmux_payload("hello agent", mode="chat")
    assert decision.decision == "allow"
    assert decision.command_class == "chat"


def test_tmux_chat_requires_approval_for_rm_rf():
    decision = evaluate_tmux_payload("rm -rf /", mode="chat")
    assert decision.decision == "needs_approval"
    assert decision.command_class == "destructive"
    assert decision.confirm_token


def test_tmux_shell_allows_ls():
    decision = evaluate_tmux_payload("ls -la", mode="shell")
    assert decision.decision == "allow"
    assert decision.command_class == "read"


def test_tmux_shell_requires_approval_for_unknown():
    decision = evaluate_tmux_payload("do_the_thing now", mode="shell")
    assert decision.decision == "needs_approval"


def test_tmux_chat_allows_shell_metacharacters_in_plain_text():
    decision = evaluate_tmux_payload("explain $PATH | grep usage", mode="chat")
    assert decision.decision == "allow"
    assert decision.command_class == "chat"


def test_tmux_shell_metacharacters_require_approval():
    decision = evaluate_tmux_payload("ls | grep py", mode="shell")
    assert decision.decision == "needs_approval"
    assert "metacharacters" in decision.reason


def test_tmux_shell_profile_allowlist_enforced():
    decision = evaluate_tmux_payload(
        "echo hi",
        mode="shell",
        profile={"allowed_verbs": ["ls", "cat"]},
    )
    assert decision.decision == "needs_approval"
    assert "allowlist" in decision.reason


def test_tmux_shell_profile_blocked_verb():
    decision = evaluate_tmux_payload(
        "rm -rf /tmp/x",
        mode="shell",
        profile={"blocked_verbs": ["rm"]},
    )
    assert decision.decision == "blocked"
