from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_patch_cli.py"


def run_patch(cwd: Path, patch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        input=patch,
        text=True,
        capture_output=True,
        check=False,
    )


def test_apply_patch_cli_add_update_and_delete(tmp_path: Path) -> None:
    result = run_patch(
        tmp_path,
        """*** Begin Patch
*** Add File: demo.txt
+alpha
+beta
*** End Patch
""",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"

    result = run_patch(
        tmp_path,
        """*** Begin Patch
*** Update File: demo.txt
@@
 alpha
-beta
+gamma
*** End Patch
""",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"

    result = run_patch(
        tmp_path,
        """*** Begin Patch
*** Delete File: demo.txt
*** End Patch
""",
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "demo.txt").exists()
