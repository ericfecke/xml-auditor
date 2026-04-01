import csv
import io
import os

from flask import Flask, Response, jsonify, render_template, request

from agents import orchestrator

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/probe", methods=["POST"])
def probe():
    data = request.get_json(force=True) or {}
    url = data.get("url") or None
    xml_text = data.get("xml_text") or None

    state = orchestrator.probe_feed(url=url, xml_text=xml_text)

    return jsonify({
        "root_tag": state.get("root_tag", ""),
        "is_gzip": state.get("is_gzip", False),
        "parent_candidates": state.get("parent_candidates", {}),
        "field_candidates": state.get("field_candidates", {}),
        "errors": state.get("errors", []),
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True) or {}
    url = data.get("url") or None
    xml_text = data.get("xml_text") or None
    parent_tag = data.get("parent_tag", "")
    field_map = data.get("field_map") or {}

    state = orchestrator.run_pipeline(
        url=url,
        xml_text=xml_text,
        parent_tag=parent_tag,
        field_map=field_map,
    )

    # Strip all_rows before sending to frontend — kept server-side for export
    cards = {}
    for card_id, card in state.get("cards", {}).items():
        cards[card_id] = {k: v for k, v in card.items() if k != "all_rows"}

    return jsonify({
        "node_count": state.get("node_count", 0),
        "cards": cards,
        "qa_flags": state.get("qa_flags", []),
        "confidence": state.get("confidence", 1.0),
        "qa_passed": state.get("qa_passed", True),
        "errors": state.get("errors", []),
    })


@app.route("/api/export_csv", methods=["POST"])
def export_csv():
    data       = request.get_json(force=True) or {}
    card_id    = data.get("card_id", "export")
    url        = data.get("url") or None
    xml_text   = data.get("xml_text") or None
    parent_tag = data.get("parent_tag", "")
    field_map  = data.get("field_map") or {}

    # Look up cached breakdown state — no re-fetch needed
    state = orchestrator.get_breakdown_cached(url, xml_text, parent_tag, field_map)
    if state is None:
        # Fallback: re-run (handles edge cases like cache expiry)
        state = orchestrator.run_pipeline(
            url=url, xml_text=xml_text,
            parent_tag=parent_tag, field_map=field_map,
        )

    card = state.get("cards", {}).get(card_id, {})
    rows = card.get("all_rows") or card.get("rows", [])

    def generate():
        if not rows:
            yield ""
            return
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writerow(row)
            yield buf.getvalue()

    filename = f"{card_id}.csv"
    return Response(
        generate(), mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
