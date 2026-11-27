"""Tests for napoln.core._version — runtime version resolution."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import pytest

import napoln
from napoln.core import _version


class TestVersionResolution:
    """Runtime version agrees with installed metadata and pyproject.toml."""

    def test_runtime_matches_installed_metadata(self) -> None:
        installed = importlib.metadata.version("napoln")
        assert _version.__version__ == installed
        assert napoln.__version__ == installed

    def test_runtime_matches_pyproject(self) -> None:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with pyproject.open("rb") as f:
            declared = tomllib.load(f)["project"]["version"]
        assert _version.__version__ == declared

    def test_falls_back_to_pyproject_when_package_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_not_found(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError("napoln")

        monkeypatch.setattr(_version, "version", raise_not_found)
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with pyproject.open("rb") as f:
            declared = tomllib.load(f)["project"]["version"]
        assert _version._get_version() == declared

    def test_falls_back_to_zero_when_pyproject_missing(self, tmp_path: Path) -> None:
        assert _version._read_pyproject_version(tmp_path / "missing.toml") == "0.0.0"
