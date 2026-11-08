"""A dependency-free MCP server over stdio.

It answers for the build that this repository pins. Every answer names the
build. Other tools can use the same data through the ./waw command line.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys

from . import __version__, checks, core, graph, snapshot

SERVER_INFO = {"name": "wow-forever", "version": __version__}
LATEST_PROTOCOL = "2025-06-18"
MAX_TEXT = 60000


def _schema(properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": properties or {}, "required": required or []}


BUILD_ARG = {"type": "integer", "description": "Build number. Omit it to use the build this repository pins."}
TOOLS = [
    {"name": "wow_target_status",
     "description": "Show the pinned WoW Forever build and compare it with the live build, the local client and the UI source. Call this first in every session.",
     "inputSchema": _schema({"offline": {"type": "boolean"}})},
    {"name": "wow_code_index",
     "description": "List the codebase-memory-mcp projects for this repository: its own code, the shared Blizzard FrameXML of the pinned build, and reference addons. Call this before you read Lua or XML files.",
     "inputSchema": _schema()},
    {"name": "wow_api_lookup",
     "description": "Look up an exact function, C_ namespace, event, enum, structure, widget method or CVar on the pinned build. Returns availability, signature, and secret or restriction flags. Call this before you use any API.",
     "inputSchema": _schema({"name": {"type": "string"}, "build": BUILD_ARG}, ["name"])},
    {"name": "wow_api_search",
     "description": "Search API names on the pinned build by substring.",
     "inputSchema": _schema({"query": {"type": "string"}, "limit": {"type": "integer"}, "build": BUILD_ARG}, ["query"])},
    {"name": "wow_api_restrictions",
     "description": "List functions and events with secret value or restriction flags, filtered by a name substring.",
     "inputSchema": _schema({"query": {"type": "string"}, "limit": {"type": "integer"}, "build": BUILD_ARG})},
    {"name": "wow_api_diff",
     "description": "Compare two synced builds. Omit from_build and to_build to compare the pinned build with the newest synced build. Set against_retail to compare Forever with the synced Midnight retail build.",
     "inputSchema": _schema({"from_build": {"type": "integer"}, "to_build": {"type": "integer"},
                             "against_retail": {"type": "boolean"}, "summary_only": {"type": "boolean"}})},
    {"name": "wow_migration_lookup",
     "description": "Find the Forever replacement for an old API or event, such as the combat log, GetSpellInfo or UnitAura.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "wow_ui_source_search",
     "description": "Search Blizzard's exported UI source for the pinned build with a regular expression. Use it to see how the client itself uses an API.",
     "inputSchema": _schema({"pattern": {"type": "string"}, "path_glob": {"type": "string"},
                             "limit": {"type": "integer"}, "build": BUILD_ARG}, ["pattern"])},
    {"name": "wow_check_addons",
     "description": "Run the static checks on the addons in this repository against the pinned build.",
     "inputSchema": _schema({"addons": {"type": "array", "items": {"type": "string"}}})},
]


class Server:
    def __init__(self):
        self.cache: dict = {}

    def api(self, args: dict) -> snapshot.Api:
        target = core.load_target()
        build = int(args.get("build") or target.build)
        return self.loaded(target.product, build)

    def loaded(self, product: str, build: int) -> snapshot.Api:
        key = (product, build)
        if key not in self.cache:
            self.cache[key] = snapshot.Api.load(product, build)
        return self.cache[key]

    # Tool implementations ---------------------------------------------------

    def wow_target_status(self, args):
        return core.status(core.load_target(), offline=bool(args.get("offline")))

    def wow_code_index(self, args):
        return graph.status(core.load_target())

    def wow_api_lookup(self, args):
        api = self.api(args)
        found = api.lookup(args["name"])
        migrations = checks.load_migrations()
        migration = migrations["functions"].get(args["name"]) or migrations["events"].get(args["name"])
        if found is None:
            return {"name": args["name"], "build": api.meta["version"], "found": False, "migration": migration,
                    "similar": api.search(args["name"].split(".")[-1], 12)}
        if migration:
            found["migration"] = migration
        return found

    def wow_api_search(self, args):
        api = self.api(args)
        return {"build": api.meta["version"], "results": api.search(args["query"], int(args.get("limit") or 40))}

    def wow_api_restrictions(self, args):
        api = self.api(args)
        return {"build": api.meta["version"], "results": api.restrictions(args.get("query", ""), int(args.get("limit") or 60))}

    def wow_api_diff(self, args):
        target = core.load_target()
        if args.get("against_retail"):
            retail = target.raw.get("retail", {})
            builds = snapshot.list_builds(retail.get("product", "wow"))
            if not builds:
                raise core.WawError("No retail snapshot. Run: ./waw api sync --retail")
            result = snapshot.diff(self.loaded(retail.get("product", "wow"), builds[-1]),
                                   self.loaded(target.product, target.build))
        else:
            builds = snapshot.list_builds(target.product)
            old = int(args.get("from_build") or target.build)
            new = int(args.get("to_build") or (builds[-1] if builds else target.build))
            result = snapshot.diff(self.loaded(target.product, old), self.loaded(target.product, new))
        if args.get("summary_only"):
            return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}
        return result

    def wow_migration_lookup(self, args):
        name = args["name"]
        migrations = checks.load_migrations()
        hit = migrations["functions"].get(name) or migrations["events"].get(name)
        needle = name.lower()
        related = [n for group in ("functions", "events") for n in migrations[group] if needle in n.lower() and n != name]
        return {"name": name, "migration": hit, "related": related[:20]}

    def wow_ui_source_search(self, args):
        target = core.load_target()
        build = int(args.get("build") or target.build)
        root = snapshot.ui_dir_for(target.product, build) / "Interface"
        if not root.is_dir():
            raise core.WawError("The UI source is missing. Run: ./waw api sync")
        regex = re.compile(args["pattern"])
        glob = args.get("path_glob") or "*"
        limit = int(args.get("limit") or 40)
        results = []
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".lua", ".xml", ".toc") or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if not fnmatch.fnmatch(rel, glob):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    results.append({"file": f"Interface/{rel}", "line": number, "text": line.strip()[:240]})
                    if len(results) >= limit:
                        return {"build": build, "results": results, "truncated": True}
        return {"build": build, "results": results, "truncated": False}

    def wow_check_addons(self, args):
        target = core.load_target()
        api = self.loaded(target.product, target.build)
        migrations = checks.load_migrations()
        findings: list = []
        addons = checks.addon_dirs(args.get("addons"))
        for addon in addons:
            findings += checks.check_addon(addon, target, api, migrations, addons)
        return {"build": api.meta["version"], "findings": checks.findings_json(findings)}

    # Protocol ---------------------------------------------------------------

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        req_id = message.get("id")
        if req_id is None:
            return None
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion")
            result = {"protocolVersion": requested or LATEST_PROTOCOL, "capabilities": {"tools": {}},
                      "serverInfo": SERVER_INFO,
                      "instructions": "Call wow_target_status first. Call wow_code_index, then query codebase-memory-mcp before you read Lua or XML files. Call wow_api_lookup before you use any WoW API. Answers apply to the pinned WoW Forever build."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = self.call_tool(message.get("params", {}))
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def call_tool(self, params: dict) -> dict:
        name = params.get("name", "")
        if name not in {t["name"] for t in TOOLS}:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
        try:
            payload = getattr(self, name)(params.get("arguments") or {})
            text = json.dumps(payload, indent=1)
            if len(text) > MAX_TEXT:
                text = text[:MAX_TEXT] + "\n... truncated. Narrow the query."
            return {"content": [{"type": "text", "text": text}]}
        except (core.WawError, KeyError, ValueError, re.error, OSError) as exc:
            return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}


def serve() -> int:
    server = Server()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        reply = server.handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0
