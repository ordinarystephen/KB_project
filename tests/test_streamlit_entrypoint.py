"""Portability check for launching Streamlit outside the repository root."""

from pathlib import Path
import subprocess
import sys


def test_streamlit_entrypoint_resolves_app_package_from_any_directory(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    code = (
        "import runpy; "
        f"runpy.run_path({str(script)!r}, run_name='streamlit_import_check')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
