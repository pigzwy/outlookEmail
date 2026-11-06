#!/usr/bin/env python3
"""Fail image builds if the application cannot load, without using live data."""

from __future__ import annotations

import importlib
import os
import secrets
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    # Override inherited settings before importing: importing initializes the DB.
    with tempfile.TemporaryDirectory(prefix="outlookemail-startup-check-") as directory:
        os.environ.update({
            "SECRET_KEY": secrets.token_hex(32),
            "DATABASE_PATH": str(Path(directory) / "startup-check.db"),
            "OUTLOOK_EMAIL_HOME": directory,
            "WERKZEUG_RUN_MAIN": "false",
        })
        sys.path.insert(0, str(ROOT_DIR))
        web = importlib.import_module("web_outlook_app")

        expected_routes = (
            ("/api/external/accounts", "GET", "api_external_get_accounts"),
            ("/api/external/accounts/tags", "POST", "api_external_manage_tags"),
        )
        for path, method, endpoint in expected_routes:
            rules = [
                rule for rule in web.app.url_map.iter_rules()
                if rule.rule == path and method in rule.methods
            ]
            if len(rules) != 1 or rules[0].endpoint != endpoint:
                raise RuntimeError(f"Unexpected route registration: {method} {path}")

        response = web.app.test_client().get("/")
        if response.status_code not in (200, 302):
            raise RuntimeError(f"Application startup request failed: {response.status_code}")

        print("Application startup check passed; external account routes are registered once.")


if __name__ == "__main__":
    main()
