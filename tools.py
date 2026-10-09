"""GitHub API tools, local repository search, and human-gated write proposals."""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import uuid

import requests

GITHUB_API = "https://api.github.com"
DEMO_REPO = os.environ.get("DEMO_REPO", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_DIR = os.environ.get("REPO_DIR", "/tmp/triage-repo")
TOOL_TIMEOUT = float(os.environ.get("TOOL_TIMEOUT", "15"))
TOOL_RETRIES = 2
MAX_FILE_LINES = 80
ALLOWED_LABELS = ("bug", "enhancement", "documentation", "question", "duplicate")
PENDING: dict[str, dict] = {}


def _scrub(text: str) -> str:
    return text.replace(GITHUB_TOKEN, "***") if GITHUB_TOKEN else text


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _github_get(path: str):
    try:
        response = requests.get(f"{GITHUB_API}{path}", headers=_headers(), timeout=10)
    except requests.RequestException as exc:
        return None, f"network error ({type(exc).__name__})"
    if response.status_code in (403, 429):
        return None, "GitHub API rate limit reached"
    if response.status_code == 404:
        return None, f"not found: {path} (check DEMO_REPO)"
    if not response.ok:
        return None, f"GitHub HTTP {response.status_code}"
    return response.json(), None


def setup() -> dict:
    """Shallow-clone the configured repository once for local code search."""
    if os.path.isdir(os.path.join(REPO_DIR, ".git")):
        return {"clone": REPO_DIR}
    if not DEMO_REPO:
        return {"error": "DEMO_REPO environment variable is not set"}
    url = f"https://github.com/{DEMO_REPO}.git"
    if GITHUB_TOKEN:
        url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{DEMO_REPO}.git"
    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", url, REPO_DIR],
                              capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"error": _scrub(f"clone failed: {type(exc).__name__}: {exc}")}
    if proc.returncode:
        return {"error": _scrub("clone failed: " + proc.stderr.decode(errors="replace")[:300])}
    return {"clone": REPO_DIR}


def get_issue(number: int) -> dict:
    """Fetch issue number, title, state, author, labels, and body."""
    data, error = _github_get(f"/repos/{DEMO_REPO}/issues/{int(number)}")
    if error:
        return {"error": error}
    return {
        "number": data["number"], "title": data["title"], "state": data["state"],
        "author": (data.get("user") or {}).get("login"),
        "labels": [label["name"] for label in data.get("labels", [])],
        "created_at": data.get("created_at"), "comments": data.get("comments", 0),
        "body": (data.get("body") or "")[:3000],
    }


def list_issues(limit: int = 15, state: str = "all") -> dict:
    """List recent issues while excluding pull requests."""
    limit = min(int(limit or 15), 50)
    if state not in ("open", "closed", "all"):
        return {"error": f"state must be open|closed|all, got {state!r}"}
    data, error = _github_get(f"/repos/{DEMO_REPO}/issues?state={state}&per_page={limit}")
    if error:
        return {"error": error}
    return {"issues": [
        {"number": item["number"], "title": item["title"], "state": item["state"]}
        for item in data if "pull_request" not in item
    ]}


def search_repo(query: str, limit: int = 10) -> dict:
    """Search text in the local shallow clone."""
    if not os.path.isdir(REPO_DIR):
        return {"error": "local clone unavailable; use list_issues instead"}
    query = str(query).lower()
    limit = min(int(limit or 10), 20)
    hits = []
    for root, dirs, filenames in os.walk(REPO_DIR):
        dirs[:] = [name for name in dirs if name not in {".git", "node_modules", "__pycache__", ".venv"}]
        for filename in filenames:
            path = os.path.join(root, filename)
            try:
                if os.path.getsize(path) > 1_000_000:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if query in line.lower():
                            relative = os.path.relpath(path, REPO_DIR)
                            hits.append(f"{relative}:{line_number}: {line.strip()[:160]}")
                            if len(hits) >= limit:
                                return {"query": query, "hits": hits}
            except OSError:
                continue
    return {"query": query, "hits": hits}


def read_file(path: str, limit: int = MAX_FILE_LINES) -> dict:
    """Read a limited number of lines from a file inside the local clone."""
    limit = min(int(limit or MAX_FILE_LINES), MAX_FILE_LINES)
    root = os.path.realpath(REPO_DIR)
    target = os.path.realpath(os.path.join(REPO_DIR, str(path)))
    if not (target == root or target.startswith(root + os.sep)):
        return {"error": "path escapes the repository"}
    try:
        with open(target, encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[:limit]
    except OSError as exc:
        return {"error": f"cannot read {path}: {exc}"}
    return {"path": path, "lines": len(lines), "content": "".join(lines)}


def propose_label(number: int, label: str) -> dict:
    """Queue a label proposal; no GitHub write occurs yet."""
    if label not in ALLOWED_LABELS:
        return {"error": f"label '{label}' is not allowed"}
    action_id = uuid.uuid4().hex[:8]
    PENDING[action_id] = {
        "type": "label", "issue": int(number), "label": label,
        "description": f"Label #{number} as '{label}'",
    }
    return {"pending_approval": action_id,
            "message": f"Proposed label for issue #{number}; waiting for human approval."}


def propose_comment(number: int, body: str) -> dict:
    """Queue a comment proposal; no GitHub write occurs yet."""
    if not str(body).strip():
        return {"error": "comment body is empty"}
    action_id = uuid.uuid4().hex[:8]
    PENDING[action_id] = {
        "type": "comment", "issue": int(number), "body": str(body),
        "description": f"Comment on #{number}: {str(body)[:80]!r}",
    }
    return {"pending_approval": action_id, "message": "Comment proposal awaits human approval."}


def pending_snapshot() -> list[dict]:
    return [{"id": key, "description": item["description"]} for key, item in PENDING.items()]


def approve(action_id: str) -> dict:
    """Apply a queued change only when a human approves it."""
    action = PENDING.get(action_id)
    if not action:
        return {"error": "unknown or already-resolved action"}
    if action["type"] == "label":
        path = f"/repos/{DEMO_REPO}/issues/{action['issue']}/labels"
        body = {"labels": [action["label"]]}
    else:
        path = f"/repos/{DEMO_REPO}/issues/{action['issue']}/comments"
        body = {"body": action["body"]}
    try:
        response = requests.post(f"{GITHUB_API}{path}", headers=_headers(), json=body, timeout=10)
    except requests.RequestException as exc:
        return {"error": f"network error: {type(exc).__name__}; proposal remains pending"}
    if not response.ok:
        return {"error": f"GitHub HTTP {response.status_code}; proposal remains pending"}
    PENDING.pop(action_id, None)
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        url = data.get("html_url")
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        url = data[0].get("html_url")
    else:
        url = None
    return {"applied": True, "url": url}


def deny(action_id: str) -> dict:
    """Discard a proposal without contacting GitHub."""
    action = PENDING.pop(action_id, None)
    if not action:
        return {"error": "unknown or already-resolved action"}
    return {"denied": True, "description": action["description"]}


TOOLS = {
    "get_issue": get_issue,
    "list_issues": list_issues,
    "search_repo": search_repo,
    "read_file": read_file,
    "propose_label": propose_label,
    "propose_comment": propose_comment,
}


def execute_tool(name: str, args: dict) -> dict | str:
    """Run a registered tool with retries and bounded wait time."""
    if name not in TOOLS:
        return f"ERROR: unknown tool '{name}'. Available: {', '.join(sorted(TOOLS))}"
    if not isinstance(args, dict):
        args = {}
    last_error = ""
    for _ in range(TOOL_RETRIES):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(TOOLS[name], **args)
                return future.result(timeout=TOOL_TIMEOUT)
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"
        except concurrent.futures.TimeoutError:
            last_error = f"ERROR: {name} timed out after {TOOL_TIMEOUT:.0f}s"
        except Exception as exc:
            last_error = f"ERROR: {name} failed: {type(exc).__name__}: {exc}"
    return _scrub(last_error)
