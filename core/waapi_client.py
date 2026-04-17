"""
WwiseTagExplorer WAAPI Client
Handles connection and data fetching from Wwise via WAAPI.
"""

import sys
import threading
import importlib.util
from collections import Counter
from pathlib import Path

_SK_WWISE_MCP = Path.home() / "sk-wwise-mcp"
_WAAPI_UTIL_PATH = _SK_WWISE_MCP / "core" / "waapi_util.py"


def _load_waapi_call():
    spec = importlib.util.spec_from_file_location(
        "sk_wwise_mcp_waapi_util", str(_WAAPI_UTIL_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    sk_path = str(_SK_WWISE_MCP)
    if sk_path not in sys.path:
        sys.path.insert(0, sk_path)
    spec.loader.exec_module(mod)
    try:
        import txaio
        txaio.set_global_log_level("critical")
    except Exception:
        pass
    return mod.call


# Category definitions: which Wwise object types belong to each category
CATEGORY_TYPES: dict[str, list[str]] = {
    "Audio": [
        "Sound", "PropertyContainer", "ActorMixer",
        "RandomSequenceContainer", "SwitchContainer", "BlendContainer",
        "Bus", "AuxBus",
    ],
    "Events": ["Event"],
    "SoundBanks": ["SoundBank"],
    "Game Syncs": ["StateGroup", "State", "SwitchGroup", "Switch", "GameParameter"],
    "ShareSets": ["Attenuation", "Effect", "Conversion"],
}

CATEGORIES = list(CATEGORY_TYPES.keys())


def parse_tags(name: str) -> list[str]:
    """
    Split an object name by underscores and return non-numeric tokens.
    e.g. 'pc_weapon_bow_shot_01' -> ['pc', 'weapon', 'bow', 'shot']
    """
    parts = name.split("_")
    return [p for p in parts if p and not p.isdigit()]


class WaapiClient:
    """Thread-safe WAAPI client wrapper for WwiseTagExplorer."""

    def __init__(self):
        self._lock = threading.Lock()
        self._call_fn = None
        self._connected = False
        self._status_callback = None
        # Cache: category -> {"objects": [...], "work_units": [...]}
        self._cache: dict[str, dict] = {}

    def set_status_callback(self, cb):
        self._status_callback = cb

    def _notify(self, connected: bool, message: str):
        self._connected = connected
        if self._status_callback:
            self._status_callback(connected, message)

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        try:
            self._call_fn = _load_waapi_call()
            result = self._call_fn("ak.wwise.core.getInfo", {})
            if result:
                version = result.get("version", {}).get("displayName", "")
                proj = self._call_fn(
                    "ak.wwise.core.object.get",
                    {"from": {"ofType": ["Project"]}, "options": {"return": ["name"]}},
                )
                proj_name = proj["return"][0]["name"] if proj and proj.get("return") else "Wwise"
                self._notify(True, f"Connected — {proj_name} ({version})")
                return True
            self._notify(False, "No response from Wwise")
            return False
        except Exception as e:
            self._notify(False, f"Failed: {str(e)[:60]}")
            return False

    def disconnect(self):
        self._call_fn = None
        self._cache.clear()
        self._notify(False, "Disconnected")

    def call(self, uri: str, args: dict = None, timeout: float = 30):
        if self._call_fn is None:
            return None
        try:
            return self._call_fn(uri, args or {}, timeout=timeout)
        except Exception as e:
            err = str(e)
            if "CannotConnect" in err or "timed out" in err.lower():
                self._notify(False, "Connection lost")
            return None

    def invalidate_cache(self, category: str = None):
        """Clear cache for a category (or all if None)."""
        if category:
            self._cache.pop(category, None)
        else:
            self._cache.clear()

    def get_category_data(self, category: str) -> dict:
        """
        Fetch all objects + work units for a category.
        Returns cached data if available.
        Result: {"objects": [...], "work_units": [...]}
        Each object: {"id", "name", "path", "type"}
        Each work_unit: {"id", "name", "path"}
        """
        if category in self._cache:
            return self._cache[category]

        types = CATEGORY_TYPES.get(category, [])
        if not types or self._call_fn is None:
            return {"objects": [], "work_units": []}

        # Fetch all objects of these types
        result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"ofType": types},
                "options": {"return": ["id", "name", "path", "type"]},
            },
            timeout=60,
        )
        objects = result.get("return", []) if result else []

        # Detect hierarchy roots from object paths
        roots: set[str] = set()
        for obj in objects:
            parts = obj.get("path", "").split("\\")
            if len(parts) >= 2:
                roots.add("\\" + parts[1])

        # Fetch all WorkUnit objects and filter to relevant roots
        wu_result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"ofType": ["WorkUnit"]},
                "options": {"return": ["id", "name", "path"]},
            },
            timeout=30,
        )
        all_wus = wu_result.get("return", []) if wu_result else []

        # Keep only Work Units that are direct children of the hierarchy roots
        # (exclude the root placeholder itself, e.g. \Containers)
        relevant_wus = []
        for wu in all_wus:
            wu_path = wu.get("path", "")
            # A Work Unit is relevant if its path starts with one of our roots
            # AND it is not the root itself
            for root in roots:
                if wu_path.startswith(root + "\\") or wu_path == root:
                    # Exclude top-level placeholders (they have no backslash after root)
                    if wu_path != root:
                        relevant_wus.append(wu)
                        break

        # Sort work units by path
        relevant_wus.sort(key=lambda w: w.get("path", ""))

        data = {"objects": objects, "work_units": relevant_wus}
        self._cache[category] = data
        return data

    def reveal_in_project_explorer(self, obj_id: str) -> bool:
        """Focus an object in the Wwise Project Explorer."""
        result = self.call(
            "ak.wwise.ui.commands.execute",
            {"command": "FindInProjectExplorerSelectionChannel1", "objects": [obj_id]},
            timeout=5,
        )
        return result is not None


# Module-level singleton
_client: WaapiClient | None = None


def get_client() -> WaapiClient:
    global _client
    if _client is None:
        _client = WaapiClient()
    return _client
