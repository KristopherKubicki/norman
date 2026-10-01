from __future__ import annotations

import re


_ACTION = (
    r"audit|build|call|check|collect|complete|connect|continue|create|deploy|dig|"
    r"do|execute|finish|fix|identify|inspect|install|investigate|look|make|open|"
    r"patch|pull|query|read|repair|report|research|resume|retry|review|run|sample|scan|"
    r"search|start|summarize|test|tighten|trace|try|update|use|verify|write"
)

PROMISED_WORK_RE = re.compile(
    rf"(?is)\b(?:"
    rf"(?:i|we)\s+(?:need|have|ought|must)\s+to|"
    rf"(?:i|we)\s+should|"
    rf"(?:i|we)(?:['\u2019]ll|\s+will|['\u2019]m|\s+am|['\u2019]re|\s+are)"
    rf"(?:\s+going\s+to)?|"
    rf"let\s+me"
    rf")[\s`*_~-]+(?:(?:first|now|next|then|still)[\s`*_~-]+)?"
    rf"(?:{_ACTION})\b"
)

IN_PROGRESS_WORK_RE = re.compile(
    r"(?is)\b(?:i|we)(?:['\u2019]m|\s+am|['\u2019]re|\s+are)\s+"
    r"(?:(?:now|next|then|still)\s+)?(?:"
    r"checking|connecting|continuing|deploying|digging|executing|finishing|"
    r"auditing|building|collecting|completing|creating|doing|fixing|identifying|"
    r"inspecting|installing|investigating|looking|making|opening|patching|"
    r"pulling|querying|reading|repairing|reporting|researching|resuming|"
    r"reviewing|running|sampling|scanning|searching|starting|summarizing|"
    r"testing|tightening|tracing|trying|updating|using|verifying|writing"
    r")\b"
)

UNFINISHED_WORK_BLOCKER_RE = re.compile(
    r"(?is)\b(?:if you want|if useful|recommended reply|client reply|what to tell|"
    r"draft reply|suggested reply|operator approval|should i|would you like|waiting for|"
    r"blocked on|cannot proceed|can['\u2019]?t proceed|need(?:s)? (?:your )?"
    r"(?:approval|authorization|confirmation|credentials|input|token)|"
    r"please (?:approve|confirm|provide)|requires? (?:approval|authorization))\b"
)

REASONING_CONTROL_BLOCK_RE = re.compile(
    r"(?is)<(?:think|thinking)>.*?</(?:think|thinking)>"
)
REASONING_CONTROL_TAG_RE = re.compile(r"(?is)</?(?:think|thinking)>")


def response_promises_unfinished_work(response: str) -> bool:
    """Return whether a final response announces work it has not performed."""

    clean = " ".join(str(response or "").split())
    if not clean or UNFINISHED_WORK_BLOCKER_RE.search(clean):
        return False
    return bool(PROMISED_WORK_RE.search(clean) or IN_PROGRESS_WORK_RE.search(clean))


def sanitize_assistant_text(response: str) -> str:
    """Remove model-private reasoning markup from user-visible assistant text."""

    text = str(response or "")
    text = REASONING_CONTROL_BLOCK_RE.sub("", text)
    text = REASONING_CONTROL_TAG_RE.sub("", text)
    return text if text.strip() else ""


def response_has_substantive_content(response: str) -> bool:
    """Return whether a response contains user-visible semantic content."""

    clean = sanitize_assistant_text(response)
    return bool(clean and re.search(r"[\w\d]", clean, flags=re.UNICODE))
