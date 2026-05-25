from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    opened_until: float = 0.0
    opens: int = 0
    last_error: str = ""


class CircuitOpen(Exception):
    def __init__(
        self, connector_id: int, opened_until: float, reason: str = ""
    ) -> None:
        super().__init__(reason or "circuit_open")
        self.connector_id = connector_id
        self.opened_until = opened_until
        self.reason = reason or "circuit_open"


class ConnectorCircuitBreaker:
    """Tiny in-memory circuit breaker keyed by connector_id.

    This complements job-level retries by quickly backing off when a connector is
    consistently failing (bad token, network outage, etc).
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        base_open_seconds: float = 20.0,
        max_open_seconds: float = 10 * 60.0,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.base_open_seconds = float(base_open_seconds)
        self.max_open_seconds = float(max_open_seconds)
        self._by_connector: Dict[int, CircuitState] = {}

    def reset(self) -> None:
        self._by_connector.clear()

    def state(self, connector_id: int) -> CircuitState:
        return self._by_connector.setdefault(int(connector_id), CircuitState())

    def is_open(self, connector_id: int, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else float(now)
        return self.state(connector_id).opened_until > now

    def opened_until(self, connector_id: int) -> float:
        return float(self.state(connector_id).opened_until)

    def record_success(self, connector_id: int) -> None:
        st = self.state(connector_id)
        st.consecutive_failures = 0
        st.opened_until = 0.0
        st.last_error = ""

    def record_failure(self, connector_id: int, error: str = "") -> CircuitState:
        now = time.time()
        st = self.state(connector_id)
        st.consecutive_failures += 1
        st.last_error = (error or "")[:512]

        if st.consecutive_failures < self.failure_threshold:
            return st

        st.opens += 1
        open_for = min(
            self.max_open_seconds, self.base_open_seconds * (2 ** max(0, st.opens - 1))
        )
        st.opened_until = now + open_for
        return st


connector_circuit_breaker = ConnectorCircuitBreaker()
