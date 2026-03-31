from copy import deepcopy


def run(state):
    state = deepcopy(state)
    try:
        node_count = state.get("node_count", 0)
        cards = state.get("cards", {})
        flags = []
        score = 1.0

        # Empty result — error
        if node_count == 0:
            flags.append({
                "field": "node_count",
                "issue": "Feed returned 0 nodes — nothing to analyze",
                "severity": "error",
            })
            score -= 0.35

        # Low node count — warn
        elif node_count < 10:
            flags.append({
                "field": "node_count",
                "issue": f"Feed has only {node_count} node(s) — may be a test feed or fetch error",
                "severity": "warn",
            })
            score -= 0.15

        # No CPC data
        cpc_rows = _get_rows(cards, "title_cpc")
        if cpc_rows and all(r.get("avg_cpc") is None for r in cpc_rows):
            flags.append({
                "field": "cpc",
                "issue": "No CPC values found — CPC field may not be mapped correctly",
                "severity": "warn",
            })
            score -= 0.15

        # No CPA data
        cpa_rows = _get_rows(cards, "title_cpa")
        if cpa_rows and all(r.get("avg_cpa") is None for r in cpa_rows):
            flags.append({
                "field": "cpa",
                "issue": "No CPA values found — CPA field may not be mapped correctly",
                "severity": "warn",
            })
            score -= 0.15

        # High missing rate: title
        if node_count > 0:
            title_rows = _get_rows(cards, "title_cpc")
            missing_title = sum(r["count"] for r in title_rows if r.get("value") == "(missing)")
            if missing_title / node_count > 0.10:
                flags.append({
                    "field": "title",
                    "issue": f"Title field missing in {missing_title}/{node_count} nodes ({missing_title/node_count:.0%})",
                    "severity": "warn",
                })
                score -= 0.15

            company_rows = _get_rows(cards, "company_cpc")
            missing_company = sum(r["count"] for r in company_rows if r.get("value") == "(missing)")
            if missing_company / node_count > 0.10:
                flags.append({
                    "field": "company",
                    "issue": f"Company field missing in {missing_company}/{node_count} nodes ({missing_company/node_count:.0%})",
                    "severity": "warn",
                })
                score -= 0.15

        # CPC outlier: any avg_cpc > 10× median
        cpc_values = [r["avg_cpc"] for r in _get_rows(cards, "title_cpc") if r.get("avg_cpc") is not None]
        if cpc_values:
            median_cpc = _median(cpc_values)
            if median_cpc > 0 and any(v > 10 * median_cpc for v in cpc_values):
                flags.append({
                    "field": "cpc",
                    "issue": "CPC outlier detected — at least one avg_cpc is >10× the median",
                    "severity": "warn",
                })
                score -= 0.15

        # CPA outlier: any avg_cpa > 10× median
        cpa_values = [r["avg_cpa"] for r in _get_rows(cards, "title_cpa") if r.get("avg_cpa") is not None]
        if cpa_values:
            median_cpa = _median(cpa_values)
            if median_cpa > 0 and any(v > 10 * median_cpa for v in cpa_values):
                flags.append({
                    "field": "cpa",
                    "issue": "CPA outlier detected — at least one avg_cpa is >10× the median",
                    "severity": "warn",
                })
                score -= 0.15

        confidence = max(0.0, round(score, 4))
        qa_passed = confidence >= 0.5

        if not qa_passed:
            for flag in flags:
                flag["suggested_action"] = _suggest(flag["field"], flag["issue"])

        state["qa_flags"] = flags
        state["confidence"] = confidence
        state["qa_passed"] = qa_passed

    except Exception as exc:
        state["errors"].append({
            "agent": "qa",
            "message": str(exc),
            "severity": "error",
        })

    return state


def _get_rows(cards, card_id):
    card = cards.get(card_id, {})
    return card.get("rows", [])


def _median(values):
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]


def _suggest(field, issue):
    suggestions = {
        "node_count": "Verify the feed URL is correct and the feed is not empty",
        "cpc": "Check CPC field mapping — common aliases: bid, cpc_value, cost_per_click, price",
        "cpa": "Check CPA field mapping — common aliases: revenue, cpa_value, cost_per_apply",
        "title": "Verify title field mapping — common aliases: job_title, jobtitle, position",
        "company": "Verify company field mapping — common aliases: advertiser, employer, employer_name",
    }
    return suggestions.get(field, "Review field mapping and feed schema")
