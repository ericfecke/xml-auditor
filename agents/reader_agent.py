import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy

KNOWN_PARENT_NAMES = {"job", "item", "listing", "result", "record", "vacancy"}


def run(state):
    state = deepcopy(state)
    try:
        content = state.get("content_bytes", b"")
        encoding = state.get("encoding", "utf-8")

        # Decode bytes for ET parsing
        try:
            xml_str = content.decode(encoding, errors="replace")
        except LookupError:
            xml_str = content.decode("utf-8", errors="replace")

        root = ET.fromstring(xml_str)
        state["root"] = root
        state["root_tag"] = _strip_ns(root.tag)

        tag_inventory = defaultdict(int)
        children_counts = defaultdict(list)   # tag -> [child_count per occurrence]
        field_candidates = defaultdict(list)  # tag -> [sample values]
        seen_for_samples = defaultdict(int)   # tag -> how many elements sampled so far

        for elem in root.iter():
            tag = _strip_ns(elem.tag)
            tag_inventory[tag] += 1
            child_count = len(list(elem))
            children_counts[tag].append(child_count)

            # Leaf element with text — collect samples
            if child_count == 0:
                text = (elem.text or "").strip()
                if text and seen_for_samples[tag] < 20:
                    if len(field_candidates[tag]) < 5:
                        field_candidates[tag].append(text)
                    seen_for_samples[tag] += 1

        # Build parent_candidates
        parent_candidates = {}
        for tag, counts in children_counts.items():
            occurrence = tag_inventory[tag]
            avg_children = sum(counts) / len(counts) if counts else 0
            if (avg_children >= 3 and occurrence >= 10) or tag in KNOWN_PARENT_NAMES:
                parent_candidates[tag] = occurrence

        state["tag_inventory"] = dict(tag_inventory)
        state["parent_candidates"] = parent_candidates
        state["field_candidates"] = {k: v for k, v in field_candidates.items()}

    except Exception as exc:
        state["errors"].append({
            "agent": "reader",
            "message": str(exc),
            "severity": "error",
        })

    return state


def _strip_ns(tag):
    # Strip XML namespace: {http://...}tagname -> tagname
    return re.sub(r"^\{[^}]+\}", "", tag)
