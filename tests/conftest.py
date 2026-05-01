import pytest


@pytest.fixture
def tmp_sessions_dir(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def tmp_config_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_dir = tmp_path
    monkeypatch.setattr("nugget.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("nugget.config.CONFIG_DIR", cfg_dir)
    return cfg_file


@pytest.fixture
def tmp_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr("nugget.tools.memory._DB_PATH", db_path)
    return db_path


@pytest.fixture
def tmp_tasks_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr("nugget.tools.tasks._DB_PATH", db_path)
    return db_path
