"""Serialize AWS side effects, including recovery, across executor processes."""

from contextlib import contextmanager
from functools import wraps
import fcntl
import os
from pathlib import Path
import stat
from typing import Any, Callable, Iterator

from app.services.aws_rotation_store import RotationError


@contextmanager
def operation_lock(path: Path) -> Iterator[None]:
    """Use one deployment-owned path; never unlink an in-use lock inode."""
    descriptor = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise RotationError("rotation_lock_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, RotationError):
        if descriptor is not None:
            os.close(descriptor)
        raise RotationError("rotation_busy_or_lock_invalid") from None
    try:
        yield
    finally:
        os.close(descriptor)


def exclusive(operation: Callable) -> Callable:
    """Hold the same lock through every external action and durable transition."""

    @wraps(operation)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with operation_lock(self.lock_path):
            return operation(self, *args, **kwargs)

    return wrapped
