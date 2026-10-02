"""Measure, on Windows, what DRIFT-004 of SPEC-0001a could not measure elsewhere.

Windows reserves CON, NUL, COM1 and friends as device names, with any extension and any
casing. Opening one for reading does not open a file: it blocks on the device. The parser
reads uploaded documents synchronously from inside an async handler, so a single upload
named CON.md would freeze the event loop and with it the whole server.

The guard that renames such a file is written and unit tested, but its end to end effect
can only be observed where the device semantics exist. That is this script's whole job.

It runs pytest in a subprocess with a timeout, because the failure being hunted is a hang:
a plain test run would not report it, it would simply never come back.

Standard library only, so it adds no dependency to run once.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SELECTION = "tests/functional/test_path_containment.py"
_FILTER = "windows_device"
_EVIDENCE = _REPO / "specs" / "SPEC-0001a_2026-10-01_14-01-27-cwe22-path-containment" / "DRIFT-004-windows-evidence.txt"
# Generous: the assertion inside the tests is 5 s each. Anything past this is the hang.
_TIMEOUT_SECONDS = 180


def _run(*args: str) -> tuple[int, str]:
    done = subprocess.run(args, cwd=_REPO, capture_output=True, text=True, check=False)
    return done.returncode, (done.stdout + done.stderr).strip()


def main() -> int:
    is_windows = platform.system() == "Windows"
    _, commit = _run("git", "rev-parse", "HEAD")
    _, branch = _run("git", "rev-parse", "--abbrev-ref", "HEAD")

    print(f"platform : {platform.system()} {platform.release()}")
    print(f"python   : {sys.version.split()[0]}")
    print(f"branch   : {branch}")
    print(f"commit   : {commit}")
    print()

    if not is_windows:
        print("This is not Windows. The four tests are skipif-guarded and would measure")
        print("nothing here. Run it on the machine that runs tgi.bat.")
        return 2

    print(f"Running the {_FILTER} tests, timeout {_TIMEOUT_SECONDS}s...")
    print()
    verdict, output = _pytest()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    _EVIDENCE.write_text(
        "\n".join(
            [
                "DRIFT-004 of SPEC-0001a: Windows device names, measured",
                "=" * 56,
                "",
                f"date     : {stamp}",
                f"platform : {platform.system()} {platform.release()} ({platform.machine()})",
                f"python   : {sys.version.split()[0]}",
                f"branch   : {branch}",
                f"commit   : {commit}",
                f"command  : uv run pytest {_SELECTION} -k {_FILTER} -v",
                "",
                f"VERDICT  : {verdict}",
                "",
                "Raw output",
                "-" * 56,
                output,
                "",
            ]
        ),
        encoding="utf-8",
    )
    print()
    print(f"VERDICT: {verdict}")
    print(f"written: {_EVIDENCE.relative_to(_REPO)}")
    return 0


def _pytest() -> tuple[str, str]:
    """Run the selection and classify the outcome, a hang included."""
    try:
        done = subprocess.run(
            ["uv", "run", "pytest", _SELECTION, "-k", _FILTER, "-v"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        captured = (
            (expired.stdout or b"").decode(errors="replace")
            if isinstance(expired.stdout, bytes)
            else (expired.stdout or "")
        )
        return (
            "HUNG - this is itself the finding: a device was opened and the event loop "
            "froze, which is the denial of service the guard exists to prevent",
            captured + f"\n\n[no output after {_TIMEOUT_SECONDS}s]",
        )

    output = (done.stdout + done.stderr).strip()
    print(output)
    if " skipped" in output and " passed" not in output:
        return "INCONCLUSIVE - everything skipped, so nothing was measured", output
    if done.returncode == 0:
        return "PASS - the guard holds on Windows, DRIFT-004 can be closed", output
    return "FAIL - a reserved device name is not confined on Windows", output


if __name__ == "__main__":
    raise SystemExit(main())
