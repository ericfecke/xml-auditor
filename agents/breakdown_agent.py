import io
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy

from .http_utils import open_stream


def run(state, parent_tag, field_map, filters=None):
    state = deepcopy(state)
    filters = {k: v for k, v in (filters or {}).items() if v}  # drop empty values
    try:
        url     = state.get("source_url")
        content = state.get("content_bytes", b"")

        if not url and not content:
            state["errors"].append({
                "agent": "breakdown",
                "message": "No feed source in state",
                "severity": "error",
            })
            return state

        state["parent_tag"] = parent_tag

        title_tag   = field_map.get("title")   or ""
        company_tag = field_map.get("company") or ""
        cpc_tag     = field_map.get("cpc")     or ""
        cpa_tag     = field_map.get("cpa")     or ""
        url_tag     = field_map.get("url")     or ""
        url2_tag    = field_map.get("url2")    or ""
        city_tag    = field_map.get("city")    or ""
        country_tag = field_map.get("country") or ""
        other_tag   = field_map.get("other")   or ""

        _acc = lambda: defaultdict(lambda: {"count": 0, "sum": 0.0, "has_metric": False})
        title_cpc_acc   = _acc(); title_cpa_acc   = _acc()
        company_cpc_acc = _acc(); company_cpa_acc = _acc()
        city_cpc_acc    = _acc(); city_cpa_acc    = _acc()
        country_cpc_acc = _acc(); country_cpa_acc = _acc()
        other_cpc_acc   = _acc(); other_cpa_acc   = _acc()
        cpc_dist_acc    = defaultdict(int)
        cpa_dist_acc    = defaultdict(int)
        url_acc         = defaultdict(int)
        url2_acc        = defaultdict(int)
        node_count      = 0

        # Single streaming pass — never holds the full feed in memory
        for node in _iter_nodes(state, parent_tag):
            node_count += 1

            title    = _get_text(node, title_tag)
            company  = _get_text(node, company_tag)
            cpc      = _parse_numeric(node, cpc_tag)
            cpa      = _parse_numeric(node, cpa_tag)
            url_val     = _get_text(node, url_tag)     if url_tag     else None
            url2_val    = _get_text(node, url2_tag)    if url2_tag    else None
            city_val    = _get_text(node, city_tag)    if city_tag    else None
            country_val = _get_text(node, country_tag) if country_tag else None
            other_val   = _get_text(node, other_tag)   if other_tag   else None

            if filters and not _matches_filters(filters, {
                "title": title, "company": company, "city": city_val,
                "country": country_val, "other": other_val,
            }):
                continue

            title_key   = title       or "(missing)"
            company_key = company     or "(missing)"
            city_key    = city_val    or "(missing)"
            country_key = country_val or "(missing)"
            other_key   = other_val   or "(missing)"

            def _accum(cpc_a, cpa_a, key):
                cpc_a[key]["count"] += 1
                if cpc is not None:
                    cpc_a[key]["sum"] += cpc; cpc_a[key]["has_metric"] = True
                cpa_a[key]["count"] += 1
                if cpa is not None:
                    cpa_a[key]["sum"] += cpa; cpa_a[key]["has_metric"] = True

            _accum(title_cpc_acc,   title_cpa_acc,   title_key)
            _accum(company_cpc_acc, company_cpa_acc, company_key)
            if city_tag:    _accum(city_cpc_acc,    city_cpa_acc,    city_key)
            if country_tag: _accum(country_cpc_acc, country_cpa_acc, country_key)
            if other_tag:   _accum(other_cpc_acc,   other_cpa_acc,   other_key)

            if cpc is not None: cpc_dist_acc[cpc] += 1
            if cpa is not None: cpa_dist_acc[cpa] += 1
            if url_val:  url_acc[url_val]   += 1
            if url2_val: url2_acc[url2_val] += 1

        state["node_count"] = node_count

        cards = {}
        cards["total_count"] = {"id": "total_count", "label": "Total Node Count", "type": "stat", "value": node_count}
        cards["title"]   = _build_combined_card("title",   "Job Title", title_cpc_acc,   title_cpa_acc)
        cards["company"] = _build_combined_card("company", "Company",   company_cpc_acc, company_cpa_acc)
        cards["cpc_dist"] = _build_cpc_dist(cpc_dist_acc)
        cards["cpa_dist"] = _build_cpa_dist(cpa_dist_acc)
        if city_tag:
            cards["city"]    = _build_combined_card("city",    "City",    city_cpc_acc,    city_cpa_acc)
        if country_tag:
            cards["country"] = _build_combined_card("country", "Country", country_cpc_acc, country_cpa_acc)
        if other_tag:
            cards["other"]   = _build_combined_card("other", other_tag, other_cpc_acc, other_cpa_acc)
        if url_tag:
            cards["url_list"]  = _build_url_card("url_list",  "Job URL",   url_acc)
        if url2_tag:
            cards["url_list2"] = _build_url_card("url_list2", "Job URL 2", url2_acc)

        state["cards"]          = cards
        state["available_tags"] = list(state.get("field_candidates", {}).keys())

    except Exception as exc:
        state["errors"].append({
            "agent": "breakdown",
            "message": str(exc),
            "severity": "error",
        })

    return state


# ---------------------------------------------------------------------------
# Streaming node iterator
# ---------------------------------------------------------------------------

def _iter_nodes(state, parent_tag):
    """Yield each fully-parsed parent_tag element from the feed stream."""
    url     = state.get("source_url")
    content = state.get("content_bytes", b"")
    is_gzip = state.get("is_gzip", False)

    if url:
        yield from _iter_nodes_url(url, is_gzip, parent_tag)
    elif content:
        yield from _iter_nodes_bytes(io.BytesIO(content), parent_tag)


def _iter_nodes_url(url, is_gzip, parent_tag):
    try:
        with open_stream(url, is_gzip) as src:
            yield from _iter_nodes_bytes(src, parent_tag)
    except Exception:
        pass


def _iter_nodes_bytes(src, parent_tag):
    depth = 0
    try:
        for event, elem in ET.iterparse(src, events=("start", "end")):
            tag = _strip_ns(elem.tag)
            if event == "start" and tag == parent_tag:
                depth += 1
            elif event == "end" and tag == parent_tag:
                depth -= 1
                if depth == 0:
                    yield elem       # caller reads children
                    elem.clear()     # then free them
    except ET.ParseError:
        pass


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _strip_ns(tag):
    return re.sub(r"^\{[^}]+\}", "", tag)


def _get_text(node, tag):
    if not tag:
        return None
    elem = node.find(tag)
    if elem is not None:
        # itertext() collects text from the element AND all descendants,
        # so <company><name>Acme</name></company> works as well as <company>Acme</company>
        text = " ".join(elem.itertext()).strip()
        return text if text else None
    # Deep search with namespace stripping
    for child in node.iter():
        if _strip_ns(child.tag) == tag:
            text = " ".join(child.itertext()).strip()
            return text if text else None
    return None


def _parse_numeric(node, tag):
    text = _get_text(node, tag)
    if text is None:
        return None
    # Strip all non-numeric characters except digits and decimal point.
    # Handles: $0.35  £0.18  €0.42  ¥120  1,200.00  and any other currency symbol.
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------

def _matches_filters(filters, field_values):
    """Return True if all filter criteria are satisfied (case-insensitive)."""
    for key, wanted in filters.items():
        actual = (field_values.get(key) or "").strip().lower()
        if actual != wanted.strip().lower():
            return False
    return True


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _build_card(card_id, label, acc, metric_key, cap):
    rows_raw = []
    for value, data in acc.items():
        count = data["count"]
        avg   = round(data["sum"] / count, 4) if data["has_metric"] and count > 0 else None
        rows_raw.append({"value": value, "count": count, metric_key: avg})

    rows_raw.sort(key=lambda r: r["count"], reverse=True)
    total_unique = len(rows_raw)
    capped       = cap is not None and total_unique > cap

    return {
        "id": card_id, "label": label,
        "total_unique": total_unique, "capped": capped,
        "rows":     rows_raw[:cap] if capped else rows_raw,  # display (capped)
        "all_rows": rows_raw,                                 # export (full)
    }


def _build_combined_card(card_id, label, cpc_acc, cpa_acc, cap=25):
    """Single card with Value | Count | Avg CPC | Avg CPA columns."""
    keys = set(cpc_acc.keys()) | set(cpa_acc.keys())
    rows_raw = []
    for key in keys:
        cpc_data = cpc_acc.get(key, {"count": 0, "sum": 0.0, "has_metric": False})
        cpa_data = cpa_acc.get(key, {"count": 0, "sum": 0.0, "has_metric": False})
        count = cpc_data["count"] or cpa_data["count"]
        avg_cpc = round(cpc_data["sum"] / count, 4) if cpc_data["has_metric"] and count > 0 else None
        avg_cpa = round(cpa_data["sum"] / count, 4) if cpa_data["has_metric"] and count > 0 else None
        rows_raw.append({"value": key, "count": count, "avg_cpc": avg_cpc, "avg_cpa": avg_cpa})

    rows_raw.sort(key=lambda r: r["count"], reverse=True)
    total_unique = len(rows_raw)
    capped = cap is not None and total_unique > cap
    return {
        "id": card_id, "label": label, "type": "combined",
        "total_unique": total_unique, "capped": capped,
        "rows":     rows_raw[:cap] if capped else rows_raw,
        "all_rows": rows_raw,
    }


def _build_cpc_dist(acc):
    rows = sorted(
        [{"cpc_value": v, "count": c} for v, c in acc.items()],
        key=lambda r: r["cpc_value"],
    )
    total = sum(r["count"] for r in rows)
    for r in rows:
        r["pct_of_total"] = round(r["count"] / total * 100, 1) if total > 0 else 0.0
    return {
        "id": "cpc_dist", "label": "CPC Value Distribution",
        "total_unique": len(rows), "capped": False,
        "rows": rows, "all_rows": rows,
    }


def _build_cpa_dist(acc):
    rows = sorted(
        [{"cpa_value": v, "count": c} for v, c in acc.items()],
        key=lambda r: r["cpa_value"],
    )
    total = sum(r["count"] for r in rows)
    for r in rows:
        r["pct_of_total"] = round(r["count"] / total * 100, 1) if total > 0 else 0.0
    return {
        "id": "cpa_dist", "label": "CPA Value Distribution",
        "total_unique": len(rows), "capped": False,
        "rows": rows, "all_rows": rows,
    }


def _build_count_card(card_id, label, acc):
    rows_raw = sorted(
        [{"value": v, "count": c} for v, c in acc.items()],
        key=lambda r: r["count"],
        reverse=True,
    )
    total_unique = len(rows_raw)
    cap = 25
    capped = total_unique > cap
    return {
        "id": card_id, "label": label,
        "total_unique": total_unique, "capped": capped,
        "rows":     rows_raw[:cap] if capped else rows_raw,
        "all_rows": rows_raw,
    }


def _build_url_card(card_id, label, acc):
    rows_raw = sorted(
        [{"url": v, "count": c} for v, c in acc.items()],
        key=lambda r: r["count"],
        reverse=True,
    )
    total_unique = len(rows_raw)
    cap = 25
    capped = total_unique > cap
    return {
        "id": card_id, "label": label,
        "total_unique": total_unique, "capped": capped,
        "rows":     rows_raw[:cap] if capped else rows_raw,
        "all_rows": rows_raw,
    }
