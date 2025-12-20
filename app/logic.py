import hashlib
import json
from typing import Any, Dict, List, Optional

def canonical_json_sha256(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]

def is_allowed(
    requester_id: str,
    requester_scopes: List[str],
    permissions: Dict[str, Any]
) -> bool:
    deny = set(permissions.get("deny_list") or [])
    if requester_id in deny:
        return False
    readers = set(permissions.get("readers") or [])
    if requester_id in readers:
        return True
    allowed_scopes = set(permissions.get("scopes") or [])
    if allowed_scopes and any(s in allowed_scopes for s in requester_scopes):
        return True
    return False
