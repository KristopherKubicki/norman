"""Fixed host transport; stdin secrets never enter command arguments or receipts."""

import json
import subprocess

from app.services.aws_rotation_store import RotationError

HOSTS = {
    "hal:kristopher": ("hal", "kristopher@192.168.2.137"),
    "norman:kristopher": ("norman", None),
    "netops:root": ("netops", "debian@192.168.2.242"),
}
VERSION = "aws-rotation-receiver-v1"
RECEIVER = "/usr/local/sbin/norman-aws-rotation-receiver"


class SSHHostTransport:
    """Use pinned server keys and the existing Norman deployment identity."""

    def call(self, consumer: str, payload: dict) -> bool:
        """Invoke one fixed receiver; discard untrusted stdout and stderr fields."""
        if consumer not in HOSTS:
            raise RotationError("rotation_host_not_allowed")
        host, destination = HOSTS[consumer]
        command = [RECEIVER]
        if destination:
            command = [
                "/usr/bin/ssh",
                "-F",
                "/dev/null",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "UserKnownHostsFile=/etc/norman-aws-rotation-known-hosts",
                "-o",
                "IdentitiesOnly=yes",
                "-i",
                "/home/kristopher/.ssh/norman_tui_deploy_ed25519",
                destination,
                "/usr/bin/sudo",
                "-n",
                *command,
            ]
        try:
            result = subprocess.run(
                command,
                input=json.dumps(payload).encode(),
                capture_output=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError()
            receipt = json.loads(result.stdout)
            return receipt == {
                "ok": True,
                "version": VERSION,
                "host": host,
                "action": payload["action"],
            }
        except Exception:
            raise RotationError("rotation_transport_failed") from None

    def dummy(self) -> bool:
        """Check delivery and profile replacement using synthetic data on all hosts."""
        return all(self.call(consumer, {"action": "dummy"}) for consumer in HOSTS)

    def ready(self, consumer: str) -> bool:
        """Check current profiles and service health without changing credentials."""
        return self.call(consumer, {"action": "ready"})

    def install(self, consumer: str, key_id: str, secret: str) -> None:
        """Deliver only through encrypted SSH or local pipe, never a shell string."""
        if not self.call(
            consumer, {"action": "install", "key_id": key_id, "secret": secret}
        ):
            raise RotationError("rotation_install_failed")

    def verify(self, consumer: str, account: str, key_id: str) -> bool:
        """Require receiver authentication and fresh SDK checks."""
        return self.call(
            consumer, {"action": "verify", "key_id": key_id, "account_id": account}
        )
