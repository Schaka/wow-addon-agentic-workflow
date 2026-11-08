"""Connect the repository to codebase-memory-mcp.

Three kinds of index exist. The Blizzard UI source and the reference addons
are shared by every repository on this computer. Each repository also has one
index of its own code.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

from . import core, snapshot

BINARY = "codebase-memory-mcp"
DATA = pathlib.Path(__file__).parent / "data" / "references.json"
READ_HINT_BYTES = 20000
CODE_SUFFIXES = (".lua", ".xml")
REFERENCE_SUFFIXES = (".lua", ".xml", ".toc", ".md")


def available() -> bool:
    return shutil.which(BINARY) is not None


def references() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def framexml_name(target: core.Target) -> str:
    return f"wow-framexml-{target.product}-{target.build}"


def reference_name(name: str) -> str:
    return f"wow-ref-{name.lower()}"


def repo_name(root: pathlib.Path | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (root or core.ROOT).name.lower()).strip("-")
    return f"repo-{slug}"


def _unwrap(data):
    """Return the tool result. Some versions wrap it in an MCP envelope."""
    if isinstance(data, dict) and "structuredContent" in data:
        return data["structuredContent"]
    if isinstance(data, dict) and isinstance(data.get("content"), list) and data["content"]:
        text = data["content"][0].get("text", "")
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}
    return data


def _call(tool: str, arguments: dict, timeout: int = 1800) -> dict:
    """Run one tool through the CLI.

    The arguments go on standard input. Without input the CLI waits for it,
    so the input is always given and then closed.
    """
    proc = subprocess.run([BINARY, "cli", tool], input=json.dumps(arguments), capture_output=True,
                          text=True, timeout=timeout)
    if proc.returncode != 0:
        raise core.WawError(f"{BINARY} {tool} failed: {proc.stderr.strip()[-300:]}")
    for line in reversed(proc.stdout.strip().splitlines()):
        if line.startswith(("{", "[")):
            return _unwrap(json.loads(line))
    raise core.WawError(f"{BINARY} {tool} returned no JSON")


def _indexed_projects() -> set[str]:
    data = _call("list_projects", {}, timeout=60)
    rows = data.get("projects", []) if isinstance(data, dict) else data
    return {row["name"] if isinstance(row, dict) else str(row) for row in rows}


def _shared_ui_root(target: core.Target) -> pathlib.Path:
    """Return the shared Blizzard UI tree. Download it if it does not exist."""
    tree = snapshot.ui_dir_for(target.product, target.build)
    if not (tree / snapshot.DOCS_DIR).is_dir():
        snapshot.sync(target.product, target.ui_source_repo, target.ui_source_branch, target.ui_source_commit)
        tree = snapshot.ui_dir_for(target.product, target.build)
    return tree / "Interface" / "AddOns"


def _reference_root(name: str, info: dict, refresh: bool) -> pathlib.Path:
    dest = core.CACHE / "references" / name
    if refresh or not dest.is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        snapshot.download_tree(info["repo"], info["branch"], dest, suffixes=REFERENCE_SUFFIXES)
    return dest


def plan(target: core.Target, names: list[str] | None = None) -> list[dict]:
    """Describe every index that this repository uses."""
    entries = [{"project": repo_name(), "kind": "this repository", "use": "The code of this repository."},
               {"project": framexml_name(target), "kind": "shared", "use": "Blizzard UI source for the pinned build."}]
    for name, info in references().items():
        if info["default"] or (names and name in names):
            entries.append({"project": reference_name(name), "kind": "shared reference", "use": info["use"],
                            "license": info["license"], "reference": name})
    return entries


def status(target: core.Target) -> dict:
    if not available():
        return {"available": False, "install": f"Install {BINARY}. Until then, use text search.", "indexes": plan(target)}
    known = _indexed_projects()
    entries = plan(target)
    for entry in entries:
        entry["indexed"] = entry["project"] in known
    return {"available": True, "indexes": entries}


def build(target: core.Target, extra: list[str] | None = None, force: bool = False, refresh: bool = False) -> list[str]:
    """Create the indexes that do not exist yet. Return one line for each index."""
    if not available():
        raise core.WawError(f"{BINARY} is not installed.")
    known = _indexed_projects()
    report: list[str] = []
    for entry in plan(target, extra):
        project = entry["project"]
        if project in known and not force and not refresh:
            report.append(f"{project}: already indexed")
            continue
        try:
            if "reference" in entry:
                path = _reference_root(entry["reference"], references()[entry["reference"]], refresh)
            elif project == repo_name():
                path = core.ROOT
            else:
                path = _shared_ui_root(target)
            result = _call("index_repository", {"repo_path": str(path), "name": project, "mode": "moderate"})
            report.append(f"{project}: {result.get('nodes', '?')} nodes")
        except (core.WawError, OSError, ValueError, subprocess.SubprocessError) as exc:
            # One failed reference must not stop the other indexes.
            report.append(f"{project}: FAILED {type(exc).__name__}: {exc}")
    return report


def _context(target: core.Target) -> str:
    state = status(target)
    if not state["available"]:
        return f"{BINARY} is not installed here. Use text search and read only the parts of files that you need."
    lines = ["Code graph projects for this repository. Query them BEFORE you read Lua or XML files. "
             "The wow-code-graph skill has the procedure."]
    missing = False
    for entry in state["indexes"]:
        missing = missing or not entry["indexed"]
        lines.append(f"- {entry['project']} ({'ready' if entry['indexed'] else 'not indexed yet'}): {entry['use']}")
    lines.append("Flow: search_graph(project=NAME, query=...), then get_code_snippet for one symbol. "
                 "For a solved problem such as a health bar, search FrameXML first, then the wow-ref projects.")
    if missing:
        lines.append("Some indexes are missing. Run ./waw index.")
    return "\n".join(lines)


def _hook_output(event: str, text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def session_hook(target: core.Target) -> int:
    """Give a new session or subagent the project names. A failure must not block work."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    try:
        text = _context(target)
    except (core.WawError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        text = f"The code graph status failed: {exc}. Use text search."
    print(_hook_output(payload.get("hook_event_name", "SessionStart"), text))
    return 0


def read_hook() -> int:
    """Remind the agent to use the graph before it reads a large or shared code file."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool_input = payload.get("tool_input") or {}
        path = pathlib.Path(tool_input.get("file_path", ""))
        if tool_input.get("limit") or path.suffix.lower() not in CODE_SUFFIXES or not path.is_file():
            return 0
        shared = "ui-source" in path.parts or "references" in path.parts
        if shared or path.stat().st_size > READ_HINT_BYTES:
            print(_hook_output("PreToolUse", f"{path.name} is large or shared reference code. Prefer search_graph and "
                                             "get_code_snippet from codebase-memory-mcp, or read one range with offset and limit."))
    except (OSError, ValueError):
        pass
    return 0
