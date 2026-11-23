"""Scaffold smoke tests -- verifies the package is importable and the CLI wires up."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

import garmin_local
from garmin_local.cli import app


def test_package_importable() -> None:
    assert garmin_local.__version__ == "0.1.0"


def test_cli_app_is_typer_instance() -> None:
    assert isinstance(app, typer.Typer)


def test_cli_has_expected_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("login", "spike", "sync", "serve"):
        assert name in result.output
