"""The image startup check must not touch inherited deployment data."""

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_startup_check_ignores_inherited_database_and_home(tmp_path):
    protected_database = tmp_path / "deployment.db"
    protected_database.write_bytes(b"do not open or migrate this database")
    protected_home = tmp_path / "deployment-home"
    protected_home.mkdir()
    secret_file = protected_home / "secret_key.txt"
    secret_file.write_text("keep-this-deployment-secret", encoding="utf-8")
    environment = dict(os.environ)
    environment.update({
        "DATABASE_PATH": str(protected_database),
        "OUTLOOK_EMAIL_HOME": str(protected_home),
        "SECRET_KEY": "inherited-deployment-secret",
        "WERKZEUG_RUN_MAIN": "true",
        "PYTHONUTF8": "1",
    })

    result = subprocess.run(
        [sys.executable, str(ROOT_DIR / "scripts" / "check_app_startup.py")],
        cwd=ROOT_DIR,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )

    assert "Application startup check passed" in result.stdout
    assert protected_database.read_bytes() == b"do not open or migrate this database"
    assert secret_file.read_text(encoding="utf-8") == "keep-this-deployment-secret"
    assert set(protected_home.iterdir()) == {secret_file}


def test_docker_build_runs_startup_check_after_copying_application():
    dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "RUN python scripts/check_app_startup.py" in dockerfile
    assert dockerfile.index("COPY . .") < dockerfile.index("RUN python scripts/check_app_startup.py")
