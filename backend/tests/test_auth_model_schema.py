"""
The ORM models and migration 0030 must describe the same schema.

Raised in review: the columns declared unique=True *and* __table_args__
declared a named unique Index for the same column, so metadata-based creation
built two uniqueness structures where the migration creates one. Model/
migration drift is the kind of thing that is invisible until an autogenerate
run proposes something alarming.
"""

from __future__ import annotations

import pathlib
import re

from app.models.user import User, UserSession

MIGRATION = pathlib.Path(__file__).parent.parent / "alembic/versions/0030_add_users_and_sessions.py"


def _unique_indexes(model) -> set[str]:
    return {ix.name for ix in model.__table__.indexes if ix.unique}


def _unique_constraints(model) -> set[str]:
    from sqlalchemy import UniqueConstraint
    return {
        c.name or "<unnamed>"
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }


def test_uniqueness_is_declared_exactly_once_per_column():
    """One mechanism per column. Both is not twice as unique, just ambiguous."""
    assert _unique_constraints(User) == set(), (
        "User declares a UNIQUE constraint as well as a unique index; "
        "migration 0030 creates only the index"
    )
    assert _unique_constraints(UserSession) == set()


def test_the_uniqueness_that_matters_is_still_declared():
    """Tightening the above must not quietly drop the guarantee."""
    assert "idx_users_email" in _unique_indexes(User)
    assert "idx_user_sessions_token_hash" in _unique_indexes(UserSession)


def test_model_indexes_match_the_migration():
    sql = MIGRATION.read_text()
    declared = {ix.name for ix in User.__table__.indexes} | {
        ix.name for ix in UserSession.__table__.indexes
    }
    created = set(re.findall(r'op\.create_index\(\s*"([^"]+)"', sql))
    assert declared == created, (
        f"model indexes {sorted(declared)} != migration indexes {sorted(created)}"
    )


def test_provisioning_and_login_agree_on_the_password_length_cap():
    """
    create_user.py enforced only a minimum while the login route capped at
    1024, so an operator could provision an account whose password could never
    authenticate — valid in the database, rejected at the door, no error saying
    why. Raised in review; these two numbers have to move together.
    """
    import importlib.util

    from app.api.routes.auth import LoginRequest

    spec = importlib.util.spec_from_file_location(
        "create_user", pathlib.Path(__file__).parent.parent / "scripts/create_user.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    route_cap = next(m.max_length for m in LoginRequest.model_fields["password"].metadata
                     if hasattr(m, "max_length"))
    assert module.MAX_PASSWORD_LEN == route_cap


def test_unique_flags_match_the_migration():
    sql = MIGRATION.read_text()
    unique_in_migration = {
        name for name, tail in re.findall(r'op\.create_index\(\s*"([^"]+)"(.*?)\)\n', sql, re.S)
        if "unique=True" in tail
    }
    declared = _unique_indexes(User) | _unique_indexes(UserSession)
    assert declared == unique_in_migration, (
        f"model unique indexes {sorted(declared)} != "
        f"migration unique indexes {sorted(unique_in_migration)}"
    )
