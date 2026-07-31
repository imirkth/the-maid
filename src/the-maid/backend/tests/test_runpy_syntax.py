"""Regression test for run.py indentation / syntax."""
import subprocess
import sys
from pathlib import Path

RUNPY = Path(__file__).parent.parent / "run.py"


def test_runpy_can_be_imported():
    """Importing run.py should not raise IndentationError."""
    # Run a minimal Python process that imports the module without executing uvicorn.
    code = f"import importlib.util; spec = importlib.util.spec_from_file_location('runpy', r'{RUNPY}'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    # exec_module will run top-level code including uvicorn.run if it's not guarded,
    # which would hang or fail. With the fix, only print() runs and the process exits.
    assert result.returncode == 0, f"Import failed: {result.stderr}"


def test_runpy_emits_ready_on_stdout():
    """Running run.py should print READY on stdout before uvicorn starts."""
    result = subprocess.run(
        [sys.executable, str(RUNPY)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert "READY" in result.stdout, f"READY missing from stdout: {result.stdout}"
    # Exit code may be non-zero if port 9473 is in use; that is fine for this test.
    assert "🧹 [The Maid] Python backend ready" in result.stdout
