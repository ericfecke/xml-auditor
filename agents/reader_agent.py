import io
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy

KNOWN_PARENT_NAMES = {"job", "item", "listing", "result", "record", "vacancy"}


def run(state):
    state = deepcopy(state)
    try:
        content = state.get("content_bytes", b"")
        if not content:
            state["errors"].append({
                "agent": "reader",
                "message": "No content to parse",
                "severity": "error",
            })
            return state

        tag_inventory = defaultdict(int)
        children_per_node = defaultdict(list)   # tag -> [child_count per occurrence]
        field_candidates = defaultdict(list)    # tag -> [sample values]
        seen_for_samples = defaultdict(int)

        root_tag = None
        elem_stack = []  # list of [tag, child_count]

        try:
            for event, elem in ET.iterparse(io.BytesIO(content), events=("start", "end")):
                tag = _strip_ns(elem.tag)

                if event == "start":
                    if root_tag is None:
                        root_tag = tag
                    tag_inventory[tag] += 1
                    elem_stack.append([tag, 0])
                    if len(elem_stack) > 1:
                        elem_stack[-2][1] += 1   # increment parent's child count

                else:  # "end"
                    if elem_stack:
                        frame = elem_stack.pop()
                        child_count = frame[1]
                        children_per_node[tag].append(child_count)

                        # Leaf: collect up to 5 sample values from first 20 nodes
                        if child_count == 0:
                            text = (elem.text or "").strip()
                            if text and seen_for_samples[tag] < 20:
                                if len(field_candidates[tag]) < 5:
                                    field_candidates[tag].append(text)
                                seen_for_samples[tag] += 1

                    elem.clear()   # free children from memory

        except ET.ParseError:
            pass   # truncated XML — use what we parsed successfully

        # Build parent_candidates
        parent_candidates = {}
        for tag, counts in children_per_node.items():
            occurrence = tag_inventory[tag]
            avg_children = sum(counts) / len(counts) if counts else 0
            if (avg_children >= 3 and occurrence >= 10) or tag in KNOWN_PARENT_NAMES:
                parent_candidates[tag] = occurrence

        state["root_tag"] = root_tag or ""
        state["root"] = None                    # not stored — breakdown uses iterparse
        state["tag_inventory"] = dict(tag_inventory)
        state["parent_candidates"] = parent_candidates
        state["field_candidates"] = dict(field_candidates)

    except Exception as exc:
        state["errors"].append({
            "agent": "reader",
            "message": str(exc),
            "severity": "error",
        })

    return state


def _strip_ns(tag):
    return re.sub(r"^\{[^}]+\}", "", tag)
