"""Unit tests for CanaryMesh CLI."""

from typer.testing import CliRunner

from canarymesh import __version__
from canarymesh.cli import app

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Dynamic traffic splitting and automated rollback edge reverse proxy" in result.stdout


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"CanaryMesh version {__version__}" in result.stdout


def test_cli_version_flags() -> None:
    for flag in ["--version", "-v"]:
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert f"CanaryMesh version {__version__}" in result.stdout
