"""Build and query per-build API snapshots from Blizzard's exported UI source."""
from __future__ import annotations

import io
import json
import pathlib
import re
import shutil
import tarfile
import urllib.error

from . import core, lua

DOCS_DIR = "Interface/AddOns/Blizzard_APIDocumentationGenerated"
DUMP_REPO = "Ketho/BlizzardInterfaceResources"
STRUCTURAL = {"Name", "Type", "Arguments", "Returns", "Documentation", "Payload", "LiteralName", "Fields"}
ALIAS_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*;?\s*(?:--.*)?$", re.M)
WRAPPER_RE = re.compile(r"^\s*function\s+([A-Za-z_]\w*)\s*\(", re.M)
UI_GLOBAL_RE = re.compile(r"^(?:function\s+([A-Za-z_]\w*)\s*\(|([A-Z][A-Za-z0-9_]*)\s*=)", re.M)
EVENT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
TEMPLATE_RE = re.compile(r"<[A-Za-z]+\b[^<>]*\bvirtual\s*=\s*\"true\"[^<>]*>", re.I)


def path_for(product: str, build: int) -> pathlib.Path:
    return core.API_DIR / f"{product}-{build}.json"


def runtime_path_for(product: str, build: int) -> pathlib.Path:
    return core.API_DIR / f"{product}-{build}.runtime.json"


def ui_dir_for(product: str, build: int) -> pathlib.Path:
    """Return the UI tree that all repositories share. An older copy in .waw still works."""
    shared = core.CACHE / "ui-source" / f"{product}-{build}"
    legacy = core.UI_DIR / f"{product}-{build}"
    return legacy if legacy.is_dir() and not shared.is_dir() else shared


def download_tree(repo: str, ref: str, dest: pathlib.Path, suffixes: tuple[str, ...] | None = None) -> None:
    """Fetch a GitHub tree as a tarball. The content stays inert data."""
    url = f"https://codeload.github.com/{repo}/tar.gz/{ref}"
    blob = core.http_get(url, timeout=300)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/", 1)
            if len(parts) != 2 or not parts[1] or not (member.isfile() or member.isdir()):
                continue
            if suffixes and member.isfile() and not member.name.lower().endswith(suffixes):
                continue
            member.name = parts[1]
            tar.extract(member, tmp, filter="data")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)


def _system_entries(system: dict) -> tuple[dict, dict, dict, dict]:
    functions, events, tables, methods = {}, {}, {}, {}
    namespace = system.get("Namespace")
    system_env = system.get("Environment", "All")
    script_object = system.get("Type") == "ScriptObject"
    for fn in system.get("Functions") or []:
        entry = {
            "system": system.get("Name"),
            "args": fn.get("Arguments") or [],
            "returns": fn.get("Returns") or [],
            "doc": fn.get("Documentation") or [],
            "env": fn.get("Environment", system_env),
            "flags": {k: v for k, v in fn.items() if k not in STRUCTURAL and k != "Environment"},
        }
        if script_object:
            methods.setdefault(fn["Name"], []).append(entry)
        else:
            functions[f"{namespace}.{fn['Name']}" if namespace else fn["Name"]] = entry
    for ev in system.get("Events") or []:
        events[ev["LiteralName"]] = {
            "system": system.get("Name"),
            "payload": ev.get("Payload") or [],
            "doc": ev.get("Documentation") or [],
            "flags": {k: v for k, v in ev.items() if k not in STRUCTURAL},
        }
    for tbl in system.get("Tables") or []:
        tables[tbl["Name"]] = {
            "kind": tbl.get("Type"),
            "system": system.get("Name"),
            "fields": tbl.get("Fields") or [],
        }
    return functions, events, tables, methods


def _flatten_strings(node, out: set[str]) -> None:
    if isinstance(node, str):
        out.add(str(node))
    elif isinstance(node, list):
        for item in node:
            _flatten_strings(item, out)
    elif isinstance(node, dict):
        for item in node.values():
            _flatten_strings(item, out)


def _dump_resources(branch: str) -> dict:
    """Read the community client dump. Its build can be older than the pin."""
    base = f"https://raw.githubusercontent.com/{DUMP_REPO}/{branch}/Resources"
    out: dict = {"globals": [], "lua": [], "events": [], "cvars": {}, "commit_subject": None}
    try:
        tables = lua.parse_top_level_tables(core.http_get(f"{base}/GlobalAPI.lua").decode("utf-8", "replace"))
        out["globals"] = sorted(str(x) for x in tables.get("GlobalAPI", []))
        out["lua"] = sorted(str(x) for x in tables.get("LuaAPI", []))
        names: set[str] = set()
        for value in lua.parse_top_level_tables(core.http_get(f"{base}/Events.lua").decode("utf-8", "replace")).values():
            _flatten_strings(value, names)
        out["events"] = sorted(n for n in names if EVENT_NAME_RE.match(n))
        cvars = lua.parse_top_level_tables(core.http_get(f"{base}/CVars.lua").decode("utf-8", "replace"))
        for group in cvars.values():
            if isinstance(group, dict):
                for section in group.values():
                    if isinstance(section, dict):
                        out["cvars"].update({str(k): v for k, v in section.items() if isinstance(v, list)})
                break
    except (urllib.error.URLError, OSError, ValueError, KeyError, lua.LuaSyntaxError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    try:
        meta = json.loads(core.http_get(f"https://api.github.com/repos/{DUMP_REPO}/commits/{branch}"))
        out["commit_subject"] = meta["commit"]["message"].splitlines()[0]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        out["commit_subject"] = "unknown build (the GitHub API did not answer)"
    return out


def read_documentation(docs: pathlib.Path) -> tuple[dict, dict, dict, dict]:
    """Read every documentation file in a folder.

    Some files hold only Tables (for example the aura sort enumerations). They have no
    Type key, so a file counts as documentation if it has Functions, Events or Tables.
    """
    functions, events, tables, methods = {}, {}, {}, {}
    for path in sorted(docs.glob("*.lua")):
        parsed = lua.parse_top_level_tables(path.read_text(encoding="utf-8", errors="replace"))
        for value in parsed.values():
            if not isinstance(value, dict) or not value.keys() & {"Functions", "Events", "Tables"}:
                continue
            f, e, t, m = _system_entries(value)
            functions.update(f)
            events.update(e)
            tables.update(t)
            for name, entries in m.items():
                methods.setdefault(name, []).extend(entries)
    return functions, events, tables, methods


def build_snapshot(tree: pathlib.Path, product: str, branch: str, commit: str, version: str) -> dict:
    functions, events, tables, methods = read_documentation(tree / DOCS_DIR)

    ui_globals: set[str] = set()
    deprecated: dict = {}
    addons = tree / "Interface" / "AddOns"
    for path in addons.rglob("*.lua"):
        rel = path.relative_to(addons).as_posix()
        if rel.startswith("Blizzard_APIDocumentation"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.startswith("Blizzard_Deprecated") or rel.startswith("Deprecated_"):
            for old, new in ALIAS_RE.findall(text):
                deprecated.setdefault(old, {"new": new, "file": rel})
            for old in WRAPPER_RE.findall(text):
                deprecated.setdefault(old, {"new": None, "file": rel})
            continue
        for fn, var in UI_GLOBAL_RE.findall(text):
            ui_globals.add(fn or var)

    dump = _dump_resources(branch)
    templates = _ui_templates(addons)
    return {
        "meta": {"product": product, "branch": branch, "commit": commit, "version": version,
                 "build": core.build_number(version), "dump_status": dump.get("error") or "ok",
                 "dump_source": dump.get("commit_subject")},
        "functions": functions, "events": events, "tables": tables, "widget_methods": methods,
        "ui_globals": sorted(ui_globals), "deprecated": deprecated, "ui_templates": templates,
        "dump_globals": dump["globals"], "dump_lua": dump["lua"], "dump_events": dump["events"],
        "cvars": dump["cvars"],
    }


def _ui_templates(addons: pathlib.Path) -> dict:
    """Index the virtual XML templates that the client defines. Map name to file."""
    templates: dict = {}
    for path in addons.rglob("*.xml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in TEMPLATE_RE.finditer(text):
            tag = match.group(0)
            if re.search(r'virtual\s*=\s*"true"', tag, re.I):
                name = re.search(r'\bname\s*=\s*"([^"]+)"', tag)
                if name:
                    templates.setdefault(name.group(1), path.relative_to(addons).as_posix())
    return templates


def sync(product: str, repo: str, branch: str, commit: str | None) -> dict:
    """Download a UI tree and write its snapshot. Return the snapshot metadata."""
    ref = commit or core.resolve_branch_head(repo, branch)
    version = core.ui_source_version(repo, ref)
    build = core.build_number(version)
    tree = ui_dir_for(product, build)
    if not (tree / DOCS_DIR).is_dir():
        tree.parent.mkdir(parents=True, exist_ok=True)
        download_tree(repo, ref, tree)
    snap = build_snapshot(tree, product, branch, ref, version)
    core.API_DIR.mkdir(parents=True, exist_ok=True)
    path_for(product, build).write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    return snap["meta"]


class Api:
    """A loaded snapshot with the availability logic used by every tool."""

    def __init__(self, data: dict, runtime: list[str] | None = None):
        self.data = data
        self.meta = data["meta"]
        self.functions = data["functions"]
        self.events = data["events"]
        self.tables = data["tables"]
        self.methods = data["widget_methods"]
        self.deprecated = data["deprecated"]
        self.cvars = data.get("cvars", {})
        self.dump_globals = set(data["dump_globals"])
        self.dump_lua = set(data["dump_lua"])
        self.dump_events = set(data["dump_events"])
        self.ui_globals = set(data["ui_globals"])
        self.runtime = set(runtime) if runtime is not None else None
        self.namespaces = {n.split(".")[0] for n in list(self.functions) + list(self.dump_globals) if "." in n}

    @classmethod
    def load(cls, product: str, build: int) -> Api:
        path = path_for(product, build)
        if not path.exists():
            raise core.WawError(f"No API snapshot for {product} build {build}. Run: ./waw api sync")
        runtime_file = runtime_path_for(product, build)
        runtime = None
        if runtime_file.exists():
            runtime = json.loads(runtime_file.read_text(encoding="utf-8")).get("functions")
        return cls(json.loads(path.read_text(encoding="utf-8")), runtime)

    def availability(self, name: str) -> dict:
        """Say whether addon code can call `name` on this build, and why."""
        fn = self.functions.get(name)
        evidence: list[str] = []
        if fn is not None:
            evidence.append("documented")
        if name in self.dump_globals or name in self.dump_lua:
            evidence.append("client-dump")
        if name in self.ui_globals:
            evidence.append("ui-source-global")
        if self.runtime is not None:
            evidence.append("runtime-probe-present" if name in self.runtime else "runtime-probe-absent")
        if fn is not None and fn["env"] == "SecureOnly":
            return {"status": "secure-only", "evidence": evidence}
        if self.runtime is not None and name in self.runtime:
            return {"status": "available", "evidence": evidence}
        if self.runtime is not None and name not in self.ui_globals and name not in self.dump_lua:
            shim = self._shim(name)
            return {"status": "deprecated-shim", "evidence": evidence, "shim": shim} if shim \
                else {"status": "absent", "evidence": evidence}
        if name in self.dump_globals or name in self.dump_lua or name in self.ui_globals:
            return {"status": "available", "evidence": evidence}
        shim = self._shim(name)
        if shim:
            return {"status": "deprecated-shim", "evidence": evidence, "shim": shim}
        if fn is not None:
            return {"status": "documented-unconfirmed", "evidence": evidence}
        return {"status": "absent", "evidence": evidence}

    def _shim(self, name: str) -> dict | None:
        """Return a working Blizzard deprecation alias, if one exists."""
        entry = self.deprecated.get(name)
        if entry is None:
            return None
        target = entry["new"]
        if target is None or self._callable(target):
            return entry
        return None

    def _callable(self, name: str) -> bool:
        fn = self.functions.get(name)
        if fn is not None:
            return fn["env"] != "SecureOnly"
        return name in self.dump_globals or name in self.ui_globals

    def event_status(self, name: str) -> dict:
        ev = self.events.get(name)
        evidence = (["documented"] if ev else []) + (["client-dump"] if name in self.dump_events else [])
        if ev is None and name not in self.dump_events:
            return {"status": "absent", "evidence": evidence}
        restricted = bool(ev and ev["flags"].get("HasRestrictions"))
        return {"status": "restricted" if restricted else "available", "evidence": evidence}

    def lookup(self, name: str) -> dict | None:
        found: dict = {"name": name, "build": self.meta["version"]}
        hit = False
        if name.startswith("Enum.") and name not in self.tables and name[5:] in self.tables:
            name = name[5:]
            found["name"] = name
        if name in self.functions or self.availability(name)["status"] != "absent" or name in self.deprecated:
            found["kind"] = "function"
            found["availability"] = self.availability(name)
            if name in self.functions:
                found["definition"] = self.functions[name]
            if name in self.deprecated:
                found["deprecated_shim"] = self.deprecated[name]
            hit = True
        if name in self.events or name in self.dump_events:
            found["event"] = {"availability": self.event_status(name), "definition": self.events.get(name)}
            hit = True
        if name in self.tables:
            found["table"] = self.tables[name]
            hit = True
        if name in self.methods:
            found["widget_method"] = self.methods[name]
            hit = True
        if name in self.cvars:
            found["cvar"] = self.cvars[name]
            hit = True
        if name in self.namespaces:
            found["namespace"] = self.namespace(name)
            hit = True
        return found if hit else None

    def namespace(self, name: str) -> list[str]:
        prefix = name + "."
        return sorted(n for n in set(self.functions) | self.dump_globals if n.startswith(prefix))

    def search(self, query: str, limit: int = 40) -> list[dict]:
        needle = query.lower()
        rows: list[tuple[int, str, str]] = []
        pools = [("function", set(self.functions) | self.dump_globals), ("event", set(self.events) | self.dump_events),
                 ("table", set(self.tables)), ("widget_method", set(self.methods)), ("cvar", set(self.cvars))]
        for kind, names in pools:
            for name in names:
                low = name.lower()
                if needle in low:
                    rank = 0 if low == needle else 1 if low.endswith(needle) or low.startswith(needle) else 2
                    rows.append((rank, name, kind))
        rows.sort()
        return [{"name": n, "kind": k} for _, n, k in rows[:limit]]

    def restrictions(self, query: str = "", limit: int = 60) -> list[dict]:
        needle = query.lower()
        out = []
        for name, entry in sorted(self.functions.items()):
            secrecy = {k: v for k, v in entry["flags"].items()
                       if k.startswith(("Secret", "HasRestrictions", "IsProtected", "Requires", "ConditionalSecret"))
                       and k != "SecretArguments"}
            if secrecy and needle in name.lower():
                out.append({"name": name, "kind": "function", "restrictions": secrecy})
        for name, entry in sorted(self.events.items()):
            secrecy = {k: v for k, v in entry["flags"].items() if k.startswith(("Secret", "HasRestrictions"))}
            if secrecy and needle in name.lower():
                out.append({"name": name, "kind": "event", "restrictions": secrecy})
        return out[:limit]


def diff(old: Api, new: Api) -> dict:
    def names(api: Api) -> dict:
        return {"functions": set(api.functions) | api.dump_globals, "events": set(api.events) | api.dump_events,
                "tables": set(api.tables)}

    def signature(entry: dict) -> str:
        return json.dumps([entry.get("args"), entry.get("returns"), entry.get("payload"), entry.get("flags")],
                          sort_keys=True)

    a, b = names(old), names(new)
    out: dict = {"from": old.meta["version"], "to": new.meta["version"]}
    for kind in a:
        out[f"{kind}_added"] = sorted(b[kind] - a[kind])
        out[f"{kind}_removed"] = sorted(a[kind] - b[kind])
    out["functions_changed"] = sorted(n for n in set(old.functions) & set(new.functions)
                                      if signature(old.functions[n]) != signature(new.functions[n]))
    out["events_changed"] = sorted(n for n in set(old.events) & set(new.events)
                                   if signature(old.events[n]) != signature(new.events[n]))
    return out


def list_builds(product: str) -> list[int]:
    if not core.API_DIR.exists():
        return []
    out = []
    for path in core.API_DIR.glob(f"{product}-*.json"):
        if not path.name.endswith(".runtime.json"):
            out.append(int(path.stem.rsplit("-", 1)[1]))
    return sorted(out)
