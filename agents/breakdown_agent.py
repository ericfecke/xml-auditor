import io
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy


def run(state, parent_tag, field_map):
    state = deepcopy(state)
    try:
        content_bytes = state.get("content_bytes", b"")
        if not content_bytes:
            state["errors"].append({
                "agent": "breakdown",
                "message": "No content bytes in state",
                "severity": "error",
            })
            return state

        state["parent_tag"] = parent_tag

        title_tag   = field_map.get("title")   or ""
        company_tag = field_map.get("company") or ""
        cpc_tag     = field_map.get("cpc")     or ""
        cpa_tag     = field_map.get("cpa")     or ""

        title_cpc_acc   = defaultdict(lambda: {"count": 0, "sum": 0.0, "has_metric": False})
        title_cpa_acc   = defaultdict(lambda: {"count": 0, "sum": 0.0, "has_metric": False})
        company_cpc_acc = defaultdict(lambda: {"count": 0, "sum": 0.0, "has_metric": False})
        company_cpa_acc = defaultdict(lambda: {"count": 0, "sum": 0.0, "has_metric": False})
        cpc_dist_acc    = defaultdict(int)

        node_count = 0

        # Single pass via iterparse — never builds the full tree in memory
        for node in _iter_nodes(content_bytes, parent_tag):
            node_count += 1

            title   = _get_text(node, title_tag)
            company = _get_text(node, company_tag)
            cpc     = _parse_numeric(node, cpc_tag)
            cpa     = _parse_numeric(node, cpa_tag)

            title_key   = title   or "(missing)"
            company_key = company or "(missing)"

            # title × CPC
            title_cpc_acc[title_key]["count"] += 1
            if cpc is not None:
                title_cpc_acc[title_key]["sum"] += cpc
                title_cpc_acc[title_key]["has_metric"] = True

            # title × CPA
            title_cpa_acc[title_key]["count"] += 1
            if cpa is not None:
                title_cpa_acc[title_key]["sum"] += cpa
                title_cpa_acc[title_key]["has_metric"] = True

            # company × CPC
            company_cpc_acc[company_key]["count"] += 1
            if cpc is not None:
                company_cpc_acc[company_key]["sum"] += cpc
                company_cpc_acc[company_key]["has_metric"] = True

            # company × CPA
            company_cpa_acc[company_key]["count"] += 1
            if cpa is not None:
                company_cpa_acc[company_key]["sum"] += cpa
                company_cpa_acc[company_key]["has_metric"] = True

            # CPC distribution
            if cpc is not None:
                cpc_dist_acc[cpc] += 1

        state["node_count"] = node_count

        cards = {}
        cards["title_cpc"]   = _build_card("title_cpc",   "Job Title × CPC",  title_cpc_acc,   "avg_cpc", cap=25)
        cards["title_cpa"]   = _build_card("title_cpa",   "Job Title × CPA",  title_cpa_acc,   "avg_cpa", cap=25)
        cards["company_cpc"] = _build_card("company_cpc", "Company × CPC",    company_cpc_acc, "avg_cpc", cap=25)
        cards["company_cpa"] = _build_card("company_cpa", "Company × CPA",    company_cpa_acc, "avg_cpa", cap=25)
        cards["cpc_dist"]    = _build_cpc_dist(cpc_dist_acc)
        cards["total_count"] = {
            "id":    "total_count",
            "label": "Total Node Count",
            "type":  "stat",
            "value": node_count,
        }

        state["cards"] = cards
        state["available_tags"] = list(state.get("field_candidates", {}).keys())

    except Exception as exc:
        state["errors"].append({
            "agent": "breakdown",
            "message": str(exc),
            "severity": "error",
        })

    return state


# ---------------------------------------------------------------------------
# Iterparse node generator
# ---------------------------------------------------------------------------

def _iter_nodes(content_bytes, parent_tag):
    """Yield each fully-parsed parent_tag element, then clear it from memory."""
    depth = 0
    try:
        for event, elem in ET.iterparse(io.BytesIO(content_bytes), events=("start", "end")):
            tag = _strip_ns(elem.tag)
            if event == "start" and tag == parent_tag:
                depth += 1
            elif event == "end" and tag == parent_tag:
                depth -= 1
                if depth == 0:
                    yield elem       # caller reads children here
                    elem.clear()     # then we free them
    except ET.ParseError:
        pass   # truncated XML — stop cleanly


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _strip_ns(tag):
    return re.sub(r"^\{[^}]+\}", "", tag)


def _get_text(node, tag):
    if not tag:
        return None
    # Direct child (no namespace)
    elem = node.find(tag)
    if elem is not None:
        text = (elem.text or "").strip()
        return text if text else None
    # Deep search with namespace stripping
    for child in node.iter():
        if _strip_ns(child.tag) == tag:
            text = (child.text or "").strip()
            return text if text else None
    return None


def _parse_numeric(node, tag):
    text = _get_text(node, tag)
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _build_card(card_id, label, acc, metric_key, cap):
    rows_raw = []
    for value, data in acc.items():
        count = data["count"]
        avg = round(data["sum"] / count, 4) if data["has_metric"] and count > 0 else None
        rows_raw.append({"value": value, "count": count, metric_key: avg})

    rows_raw.sort(key=lambda r: r["count"], reverse=True)
    total_unique = len(rows_raw)
    capped = cap is not None and total_unique > cap

    return {
        "id":          card_id,
        "label":       label,
        "total_unique": total_unique,
        "capped":      capped,
        "rows":        rows_raw[:cap] if capped else rows_raw,
    }


def _build_cpc_dist(acc):
    rows = sorted(
        [{"cpc_value": v, "count": c} for v, c in acc.items()],
        key=lambda r: r["cpc_value"],
    )
    return {
        "id":          "cpc_dist",
        "label":       "CPC Value Distribution",
        "total_unique": len(rows),
        "capped":      False,
        "rows":        rows,
    }
