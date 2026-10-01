from urllib.parse import urlsplit


def safe_local_return_to(value: str | None, default: str = "/") -> str:
    """Return a same-origin path suitable for post-authentication redirects."""
    raw = str(value or "")
    if "\\" in raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return default
    candidate = raw.strip()
    if not candidate:
        return default
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return default
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        return default
    result = parsed.path
    if parsed.query:
        result += f"?{parsed.query}"
    return result
