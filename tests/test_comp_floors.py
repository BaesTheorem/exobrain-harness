"""The job-search comp floors come from config and fail loudly when missing."""

import pytest
from conftest import load_script

cf = load_script("job-search/comp_floors.py")


def test_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_COMP_FLOOR", "12,345")
    assert cf.read_floor("JOB_COMP_FLOOR", tmp_path / "missing.env") == 12345


def test_dotenv_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_ONSITE_FLOOR", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nOTHER=1\nJOB_ONSITE_FLOOR=\"60000\"\n", encoding="utf-8")
    assert cf.read_floor("JOB_ONSITE_FLOOR", env) == 60000


def test_missing_raises_naming_example(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_COMP_FLOOR", raising=False)
    with pytest.raises(cf.FloorConfigError, match=r"\.env\.example"):
        cf.read_floor("JOB_COMP_FLOOR", tmp_path / "missing.env")


def test_non_numeric_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_COMP_FLOOR", "lots")
    with pytest.raises(cf.FloorConfigError):
        cf.read_floor("JOB_COMP_FLOOR", tmp_path / "missing.env")
