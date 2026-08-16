"""
Guards against a real bug: deploy/hetzner/.env.example once documented the
app's admin API key under the wrong variable name (OLBOS_API_KEY instead of
SECRET_KEY). Settings (pydantic-settings) only populates `secret_key` from
a var literally named SECRET_KEY and silently ignores unknown ones
(extra="ignore"), so the typo produced a live deployment with an empty
secret_key — meaning every trade-desk mutate route's require_api_key check
silently no-opped. This test makes sure the example file and the Settings
field name can't drift apart again without CI catching it.

Run with: pytest tests/test_deploy_config.py -v
"""

from pathlib import Path

from app.core.config import Settings


def _env_example_text() -> str:
    path = Path(__file__).resolve().parent.parent.parent / "deploy" / "hetzner" / ".env.example"
    assert path.exists(), f"deploy/hetzner/.env.example not found at {path}"
    return path.read_text()


def test_hetzner_env_example_uses_the_real_secret_key_var_name():
    text = _env_example_text()
    assert "SECRET_KEY=" in text, (
        "deploy/hetzner/.env.example must document SECRET_KEY (the actual "
        "Settings field name) — see app/core/config.py's `secret_key` field."
    )
    assert "OLBOS_API_KEY" not in text, (
        "OLBOS_API_KEY is not a real Settings field; a value under this name "
        "is silently ignored and secret_key stays empty (unauthenticated)."
    )


def test_secret_key_field_matches_the_documented_env_var_name():
    """Belt-and-suspenders: confirm the Settings field is still named
    exactly `secret_key` (case-insensitive-mapped from SECRET_KEY) so the
    example file's claim above stays true if config.py ever changes."""
    assert "secret_key" in Settings.model_fields
