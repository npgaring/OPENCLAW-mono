"""Regression checks for migration wiring in DB bootstrap."""
from pathlib import Path

from app.db import init_db


def test_init_db_includes_deployment_logs_and_task_build_state_migrations():
    files = init_db._MIGRATION_FILES
    assert "016_deployment_build_logs.sql" in files
    assert "017_task_build_state.sql" in files
    assert files.index("016_deployment_build_logs.sql") < files.index("017_task_build_state.sql")


def test_deployment_logs_and_task_build_state_migration_files_exist_in_active_directory():
    migrations_dir = Path(init_db.__file__).resolve().parent / "migrations"
    assert (migrations_dir / "016_deployment_build_logs.sql").exists()
    assert (migrations_dir / "017_task_build_state.sql").exists()
