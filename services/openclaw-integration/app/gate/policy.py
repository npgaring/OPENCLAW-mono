"""Policy constants for gate engine."""
import os
import re

POLICY_VERSION = "1.0.0"
REQUIRED_FIELDS = ["ocgg_identity", "plan_hash", "operations"]
FORBIDDEN_OPERATION_TYPES = {"rm_rf", "format_disk", "drop_database", "exfiltrate_data", "spawn_agent"}
MAX_OPERATIONS_PER_PLAN = 100
SCRIPT_CONTENT_BLOCKLIST = [
    re.compile(r"curl\s+.*\s+\|\s*(bash|sh)", re.I),
    re.compile(r"wget\s+.*\s+\|\s*(bash|sh)", re.I),
    re.compile(r"(bash|sh)\s+-c\s+.*(curl|wget)", re.I),
]
ALLOWED_TARGET_DOMAINS = {"allowed-domain.com"}
PROD_DEPLOYMENT_TARGETS = {"prod", "production"}
CONTRADICTION_RULES = [("no_database", "requires_auth")]
APPROVER_FIELD = "approver_id"
APPROVAL_REFERENCE_FIELD = "approval_reference"
ARTIFACT_OWNER_REGISTRY = {"artifact_A123": "Tenant_A"}


def get_policy_version_at_execution() -> str:
    return os.environ.get("POLICY_VERSION_EXECUTION_OVERRIDE") or POLICY_VERSION
