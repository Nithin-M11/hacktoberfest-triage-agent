"""Flask server for the dashboard and triage APIs."""

from __future__ import annotations

import os
from flask import Flask, jsonify, request, send_from_directory
import agent
import llm
import tools

app = Flask(__name__, static_folder="static")


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": llm.MODEL, "backend": llm.BASE_URL,
                    "repo": os.environ.get("DEMO_REPO", "")})


@app.get("/api/issues")
def issues():
    return jsonify(tools.list_issues())


@app.get("/api/pending")
def pending():
    return jsonify({"pending": tools.pending_snapshot()})


@app.post("/api/triage")
def triage():
    payload = request.get_json(silent=True) or {}
    try:
        number = int(payload.get("issue", 0))
    except (TypeError, ValueError):
        return jsonify({"error": 'body must be {"issue": <number>}'}), 400
    if number < 1:
        return jsonify({"error": "issue number must be >= 1"}), 400
    result = agent.run(number)
    result["pending_actions"] = tools.pending_snapshot()
    return jsonify(result)


@app.post("/api/propose")
def propose():
    payload = request.get_json(silent=True) or {}
    try:
        number, label = int(payload.get("issue", 0)), str(payload.get("label", ""))
    except (TypeError, ValueError):
        return jsonify({"error": 'body must be {"issue": n, "label": "..."}'}), 400
    result = tools.propose_label(number, label)
    result["pending_actions"] = tools.pending_snapshot()
    return jsonify(result), (400 if "error" in result else 200)


@app.post("/api/approve")
def approve():
    payload = request.get_json(silent=True) or {}
    action_id, decision = str(payload.get("action_id", "")), payload.get("decision")
    if not action_id or decision not in ("approve", "deny"):
        return jsonify({"error": "provide action_id and decision approve|deny"}), 400
    result = tools.approve(action_id) if decision == "approve" else tools.deny(action_id)
    return jsonify(result), (200 if result.get("applied") or result.get("denied") else 409)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8000")), threaded=True)
