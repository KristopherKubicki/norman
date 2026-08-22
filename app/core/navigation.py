from urllib.parse import urlsplit


def safe_local_return_to(value: str | None, default: str = "/") -> str:
    """Return a same-origin path suitable for post-authentication redirects."""
    candidate = str(value or "").strip()
    if not candidate:
        return default
    parsed = urlsplit(candidate)
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
