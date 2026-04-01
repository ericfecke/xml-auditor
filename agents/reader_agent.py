import gzip
import io
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy

KNOWN_PARENT_NAMES = {"job", "item", "listing", "result", "record", "vacancy"}


def run(state):
    state = deepcopy(state)
    try:
        tag_inventory     = defaultdict(int)
        children_per_node = defaultdict(list)
        field_candidates  = defaultdict(list)
        seen_for_samples  = defaultdict(int)
        root_tag          = None
        elem_stack        = []   # list of [tag, child_count]

        try:
            for event, elem in _open_stream(state):
                tag = _strip_ns(elem.tag)

                if event == "start":
                    if root_tag is None:
                        root_tag = tag
                    tag_inventory[tag] += 1
                    elem_stack.append([tag, 0])
                    if len(elem_stack) > 1:
                        elem_stack[-2][1] += 1    # increment parent child count

                else:  # "end"
                    if elem_stack:
                        frame      = elem_stack.pop()
                        child_count = frame[1]
                        children_per_node[tag].append(child_count)

                        if child_count == 0:   # leaf element — collect sample values
                            text = (elem.text or "").strip()
                            if text and seen_for_samples[tag] < 20:
                                if len(field_candidates[tag]) < 5:
                                    field_candidates[tag].append(text)
                                seen_for_samples[tag] += 1

                    elem.clear()

        except ET.ParseError:
            pass   # malformed / truncated — use what we have

        # Build parent_candidates
        parent_candidates = {}
        for tag, counts in children_per_node.items():
            occurrence   = tag_inventory[tag]
            avg_children = sum(counts) / len(counts) if counts else 0
            if (avg_children >= 3 and occurrence >= 10) or tag in KNOWN_PARENT_NAMES:
                parent_candidates[tag] = occurrence

        state["root_tag"]         = root_tag or ""
        state["root"]             = None   # never stored — breakdown re-streams
        state["tag_inventory"]    = dict(tag_inventory)
        state["parent_candidates"] = parent_candidates
        state["field_candidates"] = dict(field_candidates)

    except Exception as exc:
        state["errors"].append({
            "agent": "reader",
            "message": str(exc),
            "severity": "error",
        })

    return state


# ---------------------------------------------------------------------------
# Stream helpers (shared by reader + breakdown)
# ---------------------------------------------------------------------------

def _open_stream(state):
    """Return an iterparse iterator over the full feed — URL or paste."""
    url     = state.get("source_url")
    content = state.get("content_bytes", b"")
    is_gzip = state.get("is_gzip", False)

    if url:
        return _stream_url(url, is_gzip)
    elif content:
        return ET.iterparse(io.BytesIO(content), events=("start", "end"))
    else:
        return iter([])   # nothing to parse


def _stream_url(url, is_gzip):
    """Generator: stream-parse XML from a URL, decompressing gzip on the fly."""
    req = urllib.request.Request(url, headers={"User-Agent": "XMLAuditor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            src = gzip.GzipFile(fileobj=resp) if is_gzip else resp
            try:
                yield from ET.iterparse(src, events=("start", "end"))
            except ET.ParseError:
                pass
    except Exception:
        pass


def _strip_ns(tag):
    return re.sub(r"^\{[^}]+\}", "", tag)
