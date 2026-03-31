import hashlib
import time
from copy import deepcopy

from agents import intake_agent, reader_agent, breakdown_agent, qa_agent

FEED_CACHE = {}
CACHE_TTL = 900  # 15 minutes


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def get_cached(key):
    entry = FEED_CACHE.get(key)
    if entry and time.time() - entry["cached_at"] < CACHE_TTL:
        return entry["state"]
    return None


def set_cache(key, state):
    FEED_CACHE[key] = {"state": state, "cached_at": time.time()}


def _cache_key_for(url, xml_text):
    if url:
        return hashlib.sha256(url.encode()).hexdigest()
    if xml_text:
        text = xml_text if isinstance(xml_text, bytes) else xml_text.encode("utf-8")
        return hashlib.sha256(text).hexdigest()
    return None


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def _build_initial_state():
    return {
        # Intake
        "source_url": None,
        "raw_bytes": b"",
        "content_bytes": b"",
        "is_gzip": False,
        "encoding": "utf-8",
        "source_label": "",
        "cache_key": "",
        "errors": [],
        # Reader
        "root_tag": "",
        "root": None,
        "tag_inventory": {},
        "parent_candidates": {},
        "field_candidates": {},
        # Breakdown
        "parent_tag": "",
        "node_count": 0,
        "cards": {},
        "available_tags": [],
        # QA
        "qa_flags": [],
        "confidence": 1.0,
        "qa_passed": True,
    }


def _has_errors(state):
    return any(e.get("severity") == "error" for e in state.get("errors", []))


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def probe_feed(url=None, xml_text=None):
    """Run intake + reader only. Returns probe data for Step 1 UI."""
    state = _build_initial_state()

    pre_key = _cache_key_for(url, xml_text)
    cached = get_cached(pre_key) if pre_key else None

    if cached:
        state = deepcopy(cached)
    else:
        state = intake_agent.run(state, url=url, xml_text=xml_text)
        if _has_errors(state):
            return state
        state = reader_agent.run(state)
        if not _has_errors(state):
            # Cache uses the actual raw_bytes sha256 computed by intake
            cache_key = state.get("cache_key") or pre_key
            set_cache(cache_key, deepcopy(state))
            if pre_key and pre_key != cache_key:
                set_cache(pre_key, deepcopy(state))

    return state


def run_pipeline(url=None, xml_text=None, parent_tag=None, field_map=None):
    """Full pipeline: intake → reader (cached) → breakdown → qa."""
    field_map = field_map or {}
    state = _build_initial_state()

    pre_key = _cache_key_for(url, xml_text)
    cached = get_cached(pre_key) if pre_key else None

    if cached:
        state = deepcopy(cached)
    else:
        state = intake_agent.run(state, url=url, xml_text=xml_text)
        if _has_errors(state):
            return state
        state = reader_agent.run(state)
        if _has_errors(state):
            return state

        cache_key = state.get("cache_key") or pre_key
        set_cache(cache_key, deepcopy(state))
        if pre_key and pre_key != cache_key:
            set_cache(pre_key, deepcopy(state))

    # Breakdown and QA always re-run (field_map can differ between calls)
    state = breakdown_agent.run(state, parent_tag=parent_tag, field_map=field_map)
    state = qa_agent.run(state)
    return state
