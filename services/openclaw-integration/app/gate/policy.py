"""Policy constants for gate engine."""
import os
import re
from typing import Optional

POLICY_VERSION = "1.0.0"
REQUIRED_FIELDS = ["ocgg_identity", "plan_hash", "operations"]
FORBIDDEN_OPERATION_TYPES = {"rm_rf", "format_disk", "drop_database", "exfiltrate_data", "spawn_agent"}
MAX_OPERATIONS_PER_PLAN = 100
SCRIPT_CONTENT_BLOCKLIST = [
    re.compile(r"curl\s+.*\s+\|\s*(bash|sh)", re.I),
    re.compile(r"wget\s+.*\s+\|\s*(bash|sh)", re.I),
    re.compile(r"(bash|sh)\s+-c\s+.*(curl|wget)", re.I),
    # Command/shell injection patterns (F3)
    re.compile(r"\$\([^)]*\)"),  # $(...)
    re.compile(r"`[^`]*`"),  # backticks
    re.compile(r";\s*(bash|sh|cmd)\s", re.I),
    re.compile(r"\|\s*(bash|sh|cmd)\s", re.I),
    re.compile(r"&&\s*(bash|sh|cmd)\s", re.I),
    re.compile(r"\|\|\s*(bash|sh|cmd)\s", re.I),
    re.compile(r"\b(eval|exec)\s*\(", re.I),
]
ALLOWED_TARGET_DOMAINS = {"allowed-domain.com"}
# F1 — Filesystem: operations may only write under this logical root (path prefix).
ALLOWED_WRITE_ROOT = "/workspace"
# Path-like keys in operations/inputs that are checked for escalation.
PATH_KEYS = {"path", "dest", "output_path", "file", "target_path", "output_dir", "cwd"}
# F2 — Network: operation types or input keys that imply outbound connections.
NETWORK_OP_TYPES = {"fetch", "http_request", "request", "connect", "download", "upload"}
NETWORK_INPUT_KEYS = {"url", "host", "endpoint", "api_url"}
# F4 — Resource limits (gate blocks plans requesting above these).
MAX_MEMORY_MB = 2048
MAX_CPU_SECONDS = 300
RESOURCE_INPUT_KEYS = {"memory_mb", "memory_mb_per_op", "cpu_seconds", "timeout_seconds"}
# F5 — Only these plugin/addon IDs may be loaded.
REGISTERED_PLUGINS = {"plugin_analytics", "plugin_audit", "plugin_export"}
PLUGIN_OP_TYPES = {"load_plugin", "plugin", "addon", "load_addon"}
PLUGIN_INPUT_KEYS = {"plugin_id", "addon_id", "plugin", "addon"}
PROD_DEPLOYMENT_TARGETS = {"prod", "production"}
CONTRADICTION_RULES = [("no_database", "requires_auth")]
APPROVER_FIELD = "approver_id"
APPROVAL_REFERENCE_FIELD = "approval_reference"
ARTIFACT_OWNER_REGISTRY = {"artifact_A123": "Tenant_A"}


def get_policy_version_at_execution() -> str:
    return os.environ.get("POLICY_VERSION_EXECUTION_OVERRIDE") or POLICY_VERSION


def path_escapes_allowed_root(path: str) -> bool:
    """True if path (or its normalized form) escapes ALLOWED_WRITE_ROOT."""
    if not path or not isinstance(path, str):
        return False
    root = (ALLOWED_WRITE_ROOT or "/workspace").rstrip("/")
    is_absolute = path.lstrip().startswith("/")
    segs = path.replace("\\", "/").strip("/").split("/")
    if is_absolute:
        parts = []
        for p in segs:
            if p == "..":
                if parts:
                    parts.pop()
                else:
                    return True
            elif p and p != ".":
                parts.append(p)
        resolved = "/" + "/".join(parts) if parts else "/"
        return not (resolved == root or resolved.startswith(root + "/"))
    # Relative: treat as under root, resolve ..
    parts = [p for p in root.split("/") if p]
    for p in segs:
        if p == "..":
            if parts:
                parts.pop()
            else:
                return True
        elif p and p != ".":
            parts.append(p)
    root_count = len([p for p in root.split("/") if p])
    return len(parts) < root_count


def host_from_url_or_host(value: str) -> Optional[str]:
    """Extract hostname from URL or return value if it looks like a host."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s.startswith(("http://", "https://")):
        try:
            from urllib.parse import urlparse
            return urlparse(s).hostname or None
        except Exception:
            return None
    if "." in s or s.startswith(("localhost", "[", "::")):
        return s.split(":")[0] if ":" in s and s.startswith("[") is False else s
    return s
