"""Rendering remains responsive for long malformed markup and whitespace."""

import ast
from contextlib import contextmanager
from pathlib import Path
import re
import signal

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(
    scope="module",
    params=[
        "scripts/norman_codex_web.py",
        "scripts/agent_console_template/agent_console_web.py",
    ],
)
def patterns(request):
    tree = ast.parse((ROOT / request.param).read_text())
    namespace = {"re": re}
    names = {
        "INITIAL_HTML_TAG_RE",
        "INITIAL_OUTCOME_SIGIL_RE",
        "AUTO_TURN_CONTROL_REPORTED_DURATION_RE",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in names for t in node.targets
        ):
            exec(
                compile(
                    ast.Module(body=[node], type_ignores=[]), request.param, "exec"
                ),
                namespace,
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(r"(^|[^\w*])\*"):
                namespace["emphasis"] = re.compile(node.value)
            if node.value.startswith(r"^\s*(?:(?:please|hey|hi)"):
                namespace["status_question"] = re.compile(node.value)
    return namespace


@contextmanager
def rendering_deadline():
    """Bound regressions so an old quadratic pattern cannot hang the suite."""

    def expired(*args):
        raise AssertionError("rendering exceeded 5 seconds on malformed input")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_long_unclosed_tags_finish_quickly(patterns):
    value = "<" * 100_000
    with rendering_deadline():
        assert patterns["INITIAL_HTML_TAG_RE"].split(value) == [value]
    assert patterns["INITIAL_HTML_TAG_RE"].split('before<a href="/">link</a>after') == [
        "before",
        '<a href="/">',
        "link",
        "</a>",
        "after",
    ]


def test_blank_lines_do_not_trigger_quadratic_status_matching(patterns):
    with rendering_deadline():
        assert (
            patterns["INITIAL_OUTCOME_SIGIL_RE"].search(
                "\n" * 100_000 + "still working"
            )
            is None
        )
    match = patterns["INITIAL_OUTCOME_SIGIL_RE"].search("\n\n  DONE: complete")
    assert match.groups() == ("\n", "  ", "DONE")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("*hello*", "<em>hello</em>"),
        ("*a*", "<em>a</em>"),
        ("plain *two words* text", "plain <em>two words</em> text"),
        ("**bold**", "**bold**"),
        ("*first\nsecond*", "<em>first\nsecond</em>"),
        ("left*word*", "left*word*"),
    ],
)
def test_emphasis_semantics(patterns, value, expected):
    assert patterns["emphasis"].sub(r"\1<em>\2</em>", value) == expected


def test_unmatched_emphasis_finishes_quickly(patterns):
    value = "*x** " * 30_000
    with rendering_deadline():
        patterns["emphasis"].sub(r"\1<em>\2</em>", value)


def test_duration_and_question_whitespace_finish_quickly(patterns):
    if "status_question" not in patterns:
        pytest.skip("Only the agent template classifies route status questions")
    with rendering_deadline():
        assert (
            patterns["status_question"].match("please" + " " * 100_000 + "zzz") is None
        )
        assert (
            patterns["AUTO_TURN_CONTROL_REPORTED_DURATION_RE"].search(
                "returned" + " " * 100_000 + "zzz"
            )
            is None
        )
    assert patterns["status_question"].match("please, can you check the model")
    assert patterns["AUTO_TURN_CONTROL_REPORTED_DURATION_RE"].search("returned after ")
    assert patterns["AUTO_TURN_CONTROL_REPORTED_DURATION_RE"].search("returned ")
