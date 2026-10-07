"""Bounded connection recovery for the shared inference gateway."""


def gateway_proxy_lines(gateway_route: str, *, prefix: str = "    ") -> list[str]:
    """Retry refused dials only when Caddy can buffer the complete request."""
    lines = []
    for path, name in [("/v1/responses", "responses"), ("/v1/*", "api")]:
        lines.extend(
            [
                f"{prefix}handle {path} {{",
                # Seven decimal digits bound buffering below 10 MB. Unknown or
                # larger bodies keep the original unbuffered, non-retrying path.
                f"{prefix}    @retry_{name} header_regexp Content-Length ^[0-9]{{1,7}}$",
            ]
        )
        for matcher in [f"@retry_{name} ", ""]:
            lines.append(f"{prefix}    reverse_proxy {matcher}127.0.0.1:8000 {{")
            if name == "responses":
                lines.append(f"{prefix}        flush_interval -1")
            if matcher:
                lines.extend(
                    [
                        # Caddy 2.6 closes an unbuffered body after a refused dial.
                        f"{prefix}        buffer_requests",
                        f"{prefix}        lb_try_duration 120s",
                        f"{prefix}        lb_try_interval 250ms",
                        # Never replay a POST after the backend accepted it.
                        f"{prefix}        lb_retry_match method GET",
                    ]
                )
            lines.extend(
                [
                    f"{prefix}        header_up X-Norman-Gateway-Route {gateway_route}",
                    f"{prefix}        header_up X-Forwarded-For 127.0.0.2",
                    f"{prefix}    }}",
                ]
            )
        lines.append(f"{prefix}}}")
    return lines
