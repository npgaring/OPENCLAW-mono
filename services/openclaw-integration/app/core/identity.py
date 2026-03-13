"""Identity and domain mapping; allowed operations per identity."""
from typing import Any

IDENTITY_DOMAIN_MAP: dict[str, str] = {
    "W-OCGG": "web",
    "R-OCGG": "recruiting",
}

IDENTITY_ALLOWED_OPERATIONS: dict[str, set[str]] = {
    "W-OCGG": {"create_file", "write_config", "build", "deploy", "test", "rollback_prep"},
    "R-OCGG": {"create_file", "write_config"},
}
