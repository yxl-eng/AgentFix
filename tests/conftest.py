from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_repo(tmp_path: Path, fixtures_root: Path):
    def _copy(name: str) -> Path:
        source = fixtures_root / name
        destination = tmp_path / name
        shutil.copytree(source, destination)
        return destination

    return _copy
