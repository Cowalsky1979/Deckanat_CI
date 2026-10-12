import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

DATA = ROOT / "data"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: медленные e2e-тесты с OCR")


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA
