"""Bounded issue-triage agent. Invalid results always fall back to human review."""

from __future__ import annotations

import inspect
import json
import os

import llm
import tools
from tools import ALLOWED_LABELS, execute_tool, get_issue, setup

MAX_STEPS = int(os.environ.get("MAX_STEPS", "6"))
SEVERITIES = ("low", "medium", "high")

SYSTEM_PROMPT = """You are a GitHub issue triage agent for an open-source repository.
Each turn output exactly one JSON object.

Action:
{"thought":"brief reason","tool":"tool_name","args":{}}

Final verdict:
{"thought":"brief reason","tool":null,"verdict":{
 "labels":[],"severity":"low|medium|high","summary":"one clear paragraph",
 "next_steps":["step"],"duplicate_of":null,"confidence":0.0
}}

Available tools:
__TOOLS__

Rules:
- Use list_issues before claiming a duplicate.
- Use search_repo/read_file when the issue references code.
- propose_label/propose_comment only create proposals; a human must approve them.
- Never invent paths, issue numbers, or facts you did not observe.
- If evidence is weak, lower confidence and request human review.
- You have at most __MAX_STEPS__ steps.
"""


def _system_prompt() -> str:
    descriptions = []
    for name, fn in sorted(tools.TOOLS.items()):
        doc = (inspect.getdoc(fn) or "").split("\n")[0]
        descriptions.append(f"- {name}{inspect.signature(fn, eval_str=True)} — {doc}")
    return SYSTEM_PROMPT.replace("__TOOLS__", "\n".join(descriptions)).replace(
        "__MAX_STEPS__", str(MAX_STEPS)
    )


def validate_verdict(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    labels = raw.get("labels")
    if not isinstance(labels, list) or not all(
        isinstance(label, str) and label in ALLOWED_LABELS for label in labels
    ):
        return None
    if raw.get("severity") not in SEVERITIES:
        return None
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    steps = raw.get("next_steps", [])
    if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
        return None
    duplicate = raw.get("duplicate_of")
    if duplicate is not None and not isinstance(duplicate, int):
        return None
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    return {
        "labels": labels,
        "severity": raw["severity"],
        "summary": summary.strip(),
        "next_steps": steps,
        "duplicate_of": duplicate,
        "confidence": round(confidence, 2),
    }


def _needs_human(reason: str, log: list, raw=None) -> dict:
    result = {"needs_human": True, "reason": reason, "log": log}
    if raw is not None:
        result["rejected_verdict"] = str(raw)[:500]
    return result


def run(issue_number: int) -> dict:
    log: list[dict] = []
    setup_result = setup()
    if "error" in setup_result:
        log.append({
            "step": 0, "thought": "environment", "tool": "setup",
            "observation": setup_result["error"],
        })

    issue = get_issue(issue_number)
    if "error" in issue:
        return _needs_human(f"could not load issue #{issue_number}: {issue['error']}", log)

    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": "Triage this issue:\n" + json.dumps(issue, indent=2)[:4000]},
    ]
    last_error_key = None

    for step in range(1, MAX_STEPS + 1):
        response = llm.chat_json(messages)
        if response is None:
            return _needs_human("model output unparseable after repair retry", log)
        if "__transport_error__" in response:
            return _needs_human("LLM backend unreachable: " + response["__transport_error__"], log)

        tool_name = response.get("tool")
        if not tool_name and "verdict" not in response:
            observation = "Invalid response: expected a tool action or a final verdict JSON object."
            log.append({
                "step": step, "thought": str(response.get("thought", ""))[:400],
                "tool": "(protocol-violation)", "args": {}, "observation": observation,
            })
            messages.extend([
                {"role": "assistant", "content": json.dumps(response)},
                {"role": "user", "content": observation},
            ])
            continue

        if tool_name:
            args = response.get("args") or {}
            call_key = (str(tool_name), json.dumps(args, sort_keys=True, default=str))
            observation = execute_tool(str(tool_name), args)
            if call_key == last_error_key and str(observation).startswith("ERROR"):
                observation = str(observation) + " [Repeated failure; change approach or return a verdict.]"
            last_error_key = call_key if str(observation).startswith("ERROR") else None
            log.append({
                "step": step, "thought": str(response.get("thought", ""))[:400],
                "tool": str(tool_name), "args": args if isinstance(args, dict) else {},
                "observation": str(observation)[:600],
            })
            messages.extend([
                {"role": "assistant", "content": json.dumps(response)},
                {"role": "user", "content": "Observation: " + json.dumps(observation)[:1500]},
            ])
            continue

        verdict = validate_verdict(response.get("verdict"))
        if verdict is None:
            return _needs_human("final verdict failed validation", log, response.get("verdict"))
        return {"issue": issue_number, "needs_human": False, "verdict": verdict, "log": log}

    return _needs_human(f"step budget ({MAX_STEPS}) exhausted without a verdict", log)
