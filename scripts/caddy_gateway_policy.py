"""Bounded connection recovery for the shared inference gateway."""


def gateway_proxy_lines(gateway_route: str, *, prefix: str = "    ") -> list[str]:
    """Retry refused dials only when Caddy can buffer the complete request."""
    lines = [
        f"{prefix}handle /_gateway/status {{",
        f"{prefix}    root * /var/lib/norman/gateway-health",
        f"{prefix}    rewrite * /status.json",
        f"{prefix}    header Cache-Control no-store",
        f"{prefix}    file_server",
        f"{prefix}}}",
    ]
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


def gateway_error_lines(prefix: str = "    ") -> list[str]:
    """Explain a refused backend connection without retrying accepted requests."""
    return [
        f"{prefix}handle_errors {{",
        f"{prefix}    @gateway_down expression `{{err.status_code}} == 502 && ({{http.request.uri.path}}.startsWith('/v1/') || {{http.request.uri.path}}.startsWith('/work/v1/')) && {{err.message}}.contains('connect: connection refused')`",
        f"{prefix}    handle @gateway_down {{",
        f"{prefix}        header Content-Type application/json",
        f"{prefix}        header Retry-After 10",
        f"{prefix}        header Cache-Control no-store",
        f'{prefix}        respond `{{"error":{{"type":"gateway_unavailable","code":"backend_connection_refused","message":"Norman backend is unavailable after the recovery wait. Keep your session. Check /_gateway/status; retry after 10 seconds. Local diagnosis: codex-rescue with an explicit work or personal scope."}}}}` 503',
        f"{prefix}    }}",
        f"{prefix}}}",
    ]


def work_gateway_lines(
    allowed_clients: tuple[str, ...], *, prefix: str = "    "
) -> list[str]:
    """Expose a generic work identity without depending on an application host."""
    if not allowed_clients:
        raise ValueError("Work gateway requires an explicit client allowlist")
    return [
        f"{prefix}handle_path /work/* {{",
        f"{prefix}    @work_allowed remote_ip {' '.join(allowed_clients)}",
        f"{prefix}    handle @work_allowed {{",
        *gateway_proxy_lines("work", prefix=prefix + "        "),
        f'{prefix}        respond "not found" 404',
        f"{prefix}    }}",
        f'{prefix}    respond "forbidden" 403',
        f"{prefix}}}",
    ]
