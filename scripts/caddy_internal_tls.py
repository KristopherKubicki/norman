from __future__ import annotations


INTERNAL_LEAF_LIFETIME = "6d"


def render_internal_tls_snippet(name: str) -> str:
    snippet_name = str(name or "").strip()
    if not snippet_name:
        raise ValueError("snippet name is required")
    return f"""
({snippet_name}) {{
    tls {{
        issuer internal {{
            lifetime {INTERNAL_LEAF_LIFETIME}
        }}
    }}
}}
""".strip()
