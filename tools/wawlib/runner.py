"""Run the offline Lua tests, and the in-client bridge."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

from . import checks, core, lua, snapshot

LUA_DIR = core.ROOT / "tools" / "lua"
RUN_DIR = core.STATE / "run"
INGAME_SRC = core.ROOT / "tools" / "ingame" / "WawHarness"
HARNESS = "!WawHarness"  # The "!" makes the client load it before normal addons.
SPEC_DIR = "tests/ingame"
LUA_CANDIDATES = ("lua5.1", "lua-5.1", "lua51", "luajit", "lua")


def find_lua() -> tuple[str, str] | None:
    """Return (binary, version text) for a Lua 5.1 compatible interpreter."""
    configured = os.environ.get("WAW_LUA")
    for binary in ([configured] if configured else []) + list(LUA_CANDIDATES):
        path = shutil.which(binary)
        if path is None:
            continue
        probe = subprocess.run([path, "-e", "print(_VERSION, jit and jit.version or 'PUC')"],
                               capture_output=True, text=True)
        if probe.returncode == 0 and probe.stdout.startswith("Lua 5.1"):
            return path, probe.stdout.strip()
    return None


def _lua_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _write_string_set(handle, field: str, names) -> None:
    handle.write(f"{field}={{")
    for name in sorted(names):
        handle.write(f"[{_lua_quote(name)}]=true,")
    handle.write("},\n")


RETURN_DEFAULTS = {"number": "number", "uiUnit": "number", "bool": "boolean", "string": "string", "cstring": "string"}
SECRET_FREE_TAGS = {"Scripts"}


def _xml_tree(node, strip_scripts: bool = False) -> str:
    """Render an XML element as a Lua table constructor."""
    tag = checks._tag(node)
    attrs = ",".join(f"[{_lua_quote(k.lower())}]={_lua_quote(v)}" for k, v in node.attrib.items())
    children = ",".join(_xml_tree(child, strip_scripts) for child in node
                        if not (strip_scripts and checks._tag(child) in SECRET_FREE_TAGS))
    text = (node.text or "").strip()
    body = f",text={_lua_quote(text)}" if text else ""
    return f"{{tag={_lua_quote(tag)},attrs={{{attrs}}},children={{{children}}}{body}}}"


def _load_item(kind: str, value) -> str:
    if kind == "lua":
        return f"{{lua={_lua_quote(value)}}}"
    return f"{{xml={_xml_tree(value)}}}"


def _inherited_names(nodes) -> set[str]:
    names: set[str] = set()
    for root in nodes:
        for node in root.iter():
            for name in (checks._attr(node, "inherits") or "").split(","):
                if name.strip():
                    names.add(name.strip())
    return names


STRING_LITERAL_RE = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""")


def _lua_template_names(addons: list[pathlib.Path], known: set[str] | None = None) -> set[str]:
    """Find the templates that Lua code uses.

    A literal in the CreateFrame call is found by its position. A template name can also sit in a table
    (for example optionTemplates = { CheckButton = "InterfaceOptionsCheckButtonTemplate" }). So every string
    literal that is the name of a template of the client counts too. `known` holds those names.
    """
    names: set[str] = set()
    for addon in addons:
        for path in addon.rglob("*.lua"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in checks.CREATE_FRAME_TEMPLATE_RE.finditer(text):
                names |= {n.strip() for n in match.group(1).split(",")}
            if known:
                names |= {m for m in STRING_LITERAL_RE.findall(text) if m in known}
    return names


def _write_blizzard_templates(out, api: snapshot.Api, target: core.Target, needed: set[str]) -> None:
    """Emit the Blizzard templates that the addons use, without their scripts."""
    root = snapshot.ui_dir_for(target.product, api.meta["build"]) / "Interface" / "AddOns"
    index = api.data.get("ui_templates", {})
    parsed: dict = {}
    seen: set[str] = set()
    queue = sorted(needed)
    while queue:
        name = queue.pop()
        if name in seen or name not in index:
            continue
        seen.add(name)
        file = root / index[name]
        if file not in parsed:
            try:
                parsed[file] = ET.parse(file).getroot()
            except (ET.ParseError, OSError):
                parsed[file] = None
        tree = parsed[file]
        if tree is None:
            continue
        for node in tree.iter():
            if checks._attr(node, "name") == name and (checks._attr(node, "virtual") or "").lower() == "true":
                out.write(f"[{_lua_quote(name)}]={_xml_tree(node, strip_scripts=True)},\n")
                queue += [n for n in _inherited_names([node]) if n not in seen]
                break


def write_api_manifest(api: snapshot.Api, target: core.Target, addons: list[pathlib.Path],
                       selected: list[str] | None = None) -> pathlib.Path:
    """Write the data the Lua simulator loads: names, enums and load orders."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / "manifest.lua"
    callable_names = {name for name in set(api.functions) | api.dump_globals
                      if api.availability(name)["status"] in ("available", "documented-unconfirmed", "deprecated-shim")}
    events = {name for name in set(api.events) | api.dump_events}
    restricted = {name for name in api.events if api.event_status(name)["status"] == "restricted"}
    with path.open("w", encoding="utf-8") as out:
        out.write("return {\n")
        out.write(f"build={api.meta['build']},version={_lua_quote(target.version)},interface={target.interface},\n")
        _write_string_set(out, "functions", callable_names)
        _write_string_set(out, "events", events)
        _write_string_set(out, "restricted_events", restricted)
        out.write("widget_methods={")
        for name, entries in sorted(api.methods.items()):
            kinds = ",".join(_lua_quote(RETURN_DEFAULTS.get(r.get("Type"), "nil")) for r in entries[0]["returns"])
            out.write(f"[{_lua_quote(name)}]={{{kinds}}},")
        out.write("},\n")
        _write_string_set(out, "ui_globals", api.ui_globals)
        out.write("cvars={")
        for name, info in sorted(api.cvars.items()):
            if isinstance(info, list) and info and isinstance(info[0], str):
                out.write(f"[{_lua_quote(name)}]={_lua_quote(info[0])},")
        out.write("},\n")
        out.write("enums={\n")
        for name, table in sorted(api.tables.items()):
            if table.get("kind") != "Enumeration":
                continue
            out.write(f"[{_lua_quote(name)}]={{")
            for field in table["fields"]:
                value = field.get("EnumValue")
                if isinstance(value, (int, float)):
                    out.write(f"[{_lua_quote(field['Name'])}]={value},")
            out.write("},\n")
        names = [a.name for a in addons] if selected is None else selected
        out.write("},\nselected={" + ",".join(_lua_quote(n) for n in names) + "},\naddons={\n")
        needed: set[str] = set(_lua_template_names(addons, set(api.data.get("ui_templates", {}))))
        for addon in addons:
            toc_path = checks.active_toc(addon)
            saved: list[str] = []
            if toc_path is not None:
                tags = checks.parse_toc(toc_path).tags
                for key in ("SavedVariables", "SavedVariablesPerCharacter"):
                    saved += [v.strip() for v in tags.get(key, "").split(",") if v.strip()]
            items = checks.toc_load_items(addon, target)
            files = ",".join(_load_item(kind, value) for kind, value in items)
            needed |= _inherited_names([value for kind, value in items if kind == "xml"])
            deps = ",".join(_lua_quote(d) for d in checks.toc_dependencies(addon))
            specs = ",".join(_lua_quote(p.relative_to(core.ROOT).as_posix()) for p in sorted((addon / "tests").glob("*_spec.lua")))
            fakes = addon / "tests" / "fakes.lua"
            fakes_text = _lua_quote(fakes.relative_to(core.ROOT).as_posix()) if fakes.exists() else "nil"
            saved_text = ",".join(_lua_quote(s) for s in saved)
            out.write(f"[{_lua_quote(addon.name)}]={{dir={_lua_quote(addon.relative_to(core.ROOT).as_posix())},"
                      f"files={{{files}}},saved={{{saved_text}}},specs={{{specs}}},fakes={fakes_text},deps={{{deps}}}}},\n")
        out.write("},\ntemplates={\n")
        _write_blizzard_templates(out, api, target, needed)
        out.write("},\n}\n")
    return path


def with_dependencies(addons: list[pathlib.Path]) -> list[pathlib.Path]:
    """Return the addons and everything that they list in ## Dependencies, from the folder addons/."""
    available = {p.name: p for p in checks.addon_dirs()}
    result: list[pathlib.Path] = []
    queue = list(addons)
    while queue:
        addon = queue.pop(0)
        if addon in result:
            continue
        result.append(addon)
        queue += [available[name] for name in checks.toc_dependencies(addon) if name in available]
    return result


def run_offline(api: snapshot.Api, target: core.Target, addons: list[pathlib.Path], filter_text: str | None) -> int:
    found = find_lua()
    if found is None:
        raise core.WawError("No Lua 5.1 interpreter found. Install lua5.1 or luajit, or set WAW_LUA.")
    binary, version = found
    # A dependency must be in the manifest, or the simulator cannot load it. Only the chosen addons run tests.
    manifest = write_api_manifest(api, target, with_dependencies(addons), [a.name for a in addons])
    print(f"lua: {version}")
    env = dict(os.environ, LUA_PATH=f"{LUA_DIR.as_posix()}/?.lua;;")
    command = [binary, str(LUA_DIR / "run.lua"), str(manifest)] + ([filter_text] if filter_text else [])
    return subprocess.run(command, cwd=core.ROOT, env=env).returncode


# --- In-client bridge -------------------------------------------------------
# The client reads Lua at login or /reload and writes SavedVariables at /reload
# or logout. A person types /reload. Nothing here sends input to the game.

def addons_folder(client: pathlib.Path) -> pathlib.Path:
    return client / "Interface" / "AddOns"


def link_addons(client: pathlib.Path, addons: list[pathlib.Path], copy: bool = False) -> list[str]:
    folder = addons_folder(client)
    folder.mkdir(parents=True, exist_ok=True)
    report = []
    for addon in addons:
        dest = folder / addon.name
        if dest.is_symlink() or _is_junction(dest):
            if dest.resolve() == addon.resolve():
                report.append(f"{addon.name}: already linked")
                continue
            raise core.WawError(f"{dest} links to {dest.resolve()}. Remove that link first.")
        if dest.exists():
            marker = dest / ".waw-copy"
            if not (copy and marker.exists()):
                raise core.WawError(f"{dest} exists and waw does not own it. Move it away first.")
            shutil.rmtree(dest)
        if copy:
            shutil.copytree(addon, dest, ignore=shutil.ignore_patterns("tests"))
            (dest / ".waw-copy").write_text("created by waw\n", encoding="utf-8")
            report.append(f"{addon.name}: copied")
        else:
            _make_link(addon, dest)
            report.append(f"{addon.name}: linked")
    return report


def _is_junction(path: pathlib.Path) -> bool:
    return hasattr(path, "is_junction") and path.is_junction()


def _make_link(source: pathlib.Path, dest: pathlib.Path) -> None:
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dest), str(source)], check=True, capture_output=True)
    else:
        dest.symlink_to(source, target_is_directory=True)


def unlink_addons(client: pathlib.Path, addons: list[pathlib.Path]) -> list[str]:
    report = []
    for addon in addons:
        dest = addons_folder(client) / addon.name
        if dest.is_symlink() or _is_junction(dest):
            dest.unlink() if dest.is_symlink() else os.rmdir(dest)
            report.append(f"{addon.name}: unlinked")
        elif (dest / ".waw-copy").exists():
            shutil.rmtree(dest)
            report.append(f"{addon.name}: removed copy")
    return report


def prepare_ingame(client: pathlib.Path, addons: list[pathlib.Path], target: core.Target, probe: bool) -> dict:
    """Link addons and write the harness and specs for one test run."""
    report = link_addons(client, addons)
    folder = addons_folder(client) / HARNESS
    if folder.is_symlink():
        raise core.WawError(f"{folder} is a link. Remove it first.")
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(INGAME_SRC / "WawHarness.toc", folder / f"{HARNESS}.toc")
    shutil.copyfile(INGAME_SRC / "Core.lua", folder / "Core.lua")

    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    parts: list[str] = []
    line_map: list[dict] = []
    line = 1
    for addon in addons:
        for spec in sorted((addon / SPEC_DIR).glob("*.lua")):
            rel = spec.relative_to(core.ROOT).as_posix()
            source = spec.read_text(encoding="utf-8")
            header = f"WawHarness.define({_lua_quote(addon.name)}, {_lua_quote(rel)}, function()\n"
            footer = "\nend)\n"
            parts.append(header + source + footer)
            line_map.append({"first": line + 1, "file": rel})
            line += (header + source + footer).count("\n")
    (folder / "Specs.lua").write_text("".join(parts) or "-- No in-game specs.\n", encoding="utf-8")
    names = ",".join(_lua_quote(a.name) for a in addons)
    (folder / "Manifest.lua").write_text(
        "WawHarnessManifest = {"
        f"run_id={_lua_quote(run_id)},probe={'true' if probe else 'false'},"
        f"expected_build={target.build},expected_interface={target.interface},addons={{{names}}}}}\n",
        encoding="utf-8")

    state_dir = core.STATE / "ingame"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {"run_id": run_id, "line_map": line_map, "probe": probe, "addons": [a.name for a in addons],
             "client": str(client), "prepared_at": time.time()}
    (state_dir / "last_run.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    return {"run_id": run_id, "links": report, "specs": len(line_map), "client": str(client)}


def _saved_files(client: pathlib.Path) -> list[pathlib.Path]:
    return sorted((client / "WTF" / "Account").glob(f"*/SavedVariables/{HARNESS}.lua"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _read_run(client: pathlib.Path, run_id: str) -> dict | None:
    for path in _saved_files(client):
        db = lua.parse_saved_variables(path.read_text(encoding="utf-8", errors="replace")).get("WawHarnessDB")
        if isinstance(db, dict):
            run = (db.get("runs") or {}).get(run_id)
            if isinstance(run, dict):
                return run
    return None


def _remap_lines(text: str, line_map: list[dict]) -> str:
    def repl(match: re.Match) -> str:
        number = int(match.group(1))
        owner = None
        for entry in line_map:
            if entry["first"] <= number:
                owner = entry
        return f"{owner['file']}:{number - owner['first'] + 1}" if owner else match.group(0)
    return re.sub(r"[^\s\"']*Specs\.lua\"?\]?:(\d+)", repl, text)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value[k] for k in sorted(value, key=str)]
    return []


def _is_ours(error: dict, addons: list[str]) -> bool:
    """Decide whether a repository addon caused a recorded client error."""
    if error.get("addon") in addons:
        return True
    text = f"{error.get('message', '')}\n{error.get('stack', '')}"
    return any(re.search(rf"AddOns[/\\]{re.escape(name)}[/\\]", text) for name in [*addons, HARNESS])


def collect_errors(wait_seconds: int, as_json: bool, show_all: bool) -> int:
    """Read the Lua errors of the last client session. A /reload saves them."""
    client = core.require_client()
    addons = [a.name for a in checks.addon_dirs()]
    started = time.time()
    deadline = time.monotonic() + wait_seconds
    files = _saved_files(client)
    while wait_seconds and time.monotonic() < deadline and not (files and files[0].stat().st_mtime >= started):
        time.sleep(2)
        files = _saved_files(client)
    if not files:
        print("No harness data. Run ./waw ingame prepare, then ask the user to /reload twice.")
        return 3
    db = lua.parse_saved_variables(files[0].read_text(encoding="utf-8", errors="replace")).get("WawHarnessDB") or {}
    session = db.get("session") or {}
    errors = _as_list(session.get("errors"))
    ours = [e for e in errors if _is_ours(e, addons)]
    log_lines: list[str] = []
    for name in ("FrameXML.log", "taint.log"):
        log = client / "Logs" / name
        if log.exists():
            log_lines += [f"{name}: {ln}" for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                          if any(addon in ln for addon in addons)]
    age = int(time.time() - files[0].stat().st_mtime)
    if as_json:
        print(json.dumps({"build": session.get("build"), "saved_seconds_ago": age, "ours": ours,
                          "others": len(errors) - len(ours), "all": errors if show_all else None, "logs": log_lines}, indent=1))
    else:
        print(f"session on build {session.get('build')}, saved {age} seconds ago, source {session.get('source')}")
        for error in (errors if show_all else ours):
            print(f"[{error.get('kind')}] x{error.get('count', 1)} {error.get('message')}")
            if error.get("stack"):
                print("    " + str(error["stack"]).strip().replace("\n", "\n    "))
        for line in log_lines:
            print(line)
        print(f"{len(ours)} errors from this repository, {len(errors) - len(ours)} from other addons")
    return 1 if ours or log_lines else 0


def collect_ingame(wait_seconds: int, as_json: bool) -> int:
    state_file = core.STATE / "ingame" / "last_run.json"
    if not state_file.exists():
        raise core.WawError("No prepared run. Run: ./waw ingame prepare")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    client = pathlib.Path(state["client"])
    run_id = state["run_id"]
    deadline = time.monotonic() + wait_seconds
    run = _read_run(client, run_id)
    while run is None and time.monotonic() < deadline:
        time.sleep(2)
        run = _read_run(client, run_id)
    if run is None:
        print(f"No results for run {run_id}. In the client, type /reload, wait for the WAW result line, then type /reload again.")
        return 3

    target = core.load_target()
    tests = _as_list(run.get("tests"))
    for test in tests:
        if test.get("error"):
            test["error"] = _remap_lines(str(test["error"]), state["line_map"])
    client_errors = _as_list(run.get("client_errors"))
    failed = [t for t in tests if t.get("status") == "fail"]
    attributed = [e for e in client_errors if _is_ours(e, state["addons"])]
    build = int(run.get("build") or 0)
    result = {"run_id": run_id, "build": build, "interface": run.get("interface"), "project_id": run.get("project_id"),
              "pinned_build": target.build, "build_matches_pin": build == target.build,
              "passed": len([t for t in tests if t.get("status") == "pass"]), "failed": len(failed),
              "client_errors": client_errors, "tests": tests, "addons": run.get("addons"),
              "restrictions": run.get("restrictions"), "report": run.get("report")}
    if run.get("report"):
        out = core.STATE / "ingame" / "report.json"
        out.write_text(json.dumps(run["report"], indent=1, default=str), encoding="utf-8")
        result["report_saved"] = str(out.relative_to(core.ROOT))

    probe_functions = _as_list(run.get("probe_functions"))
    if probe_functions:
        out = snapshot.runtime_path_for(target.product, build)
        core.API_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"build": build, "functions": sorted(map(str, probe_functions))}), encoding="utf-8")
        result["probe_saved"] = str(out)

    if as_json:
        print(json.dumps(result, indent=1))
    else:
        print(f"run {run_id}: build {build}, interface {run.get('interface')}, WOW_PROJECT_ID {run.get('project_id')}")
        if build != target.build:
            print(f"warning: the client build {build} differs from the pinned build {target.build}")
        for name, info in (run.get("addons") or {}).items():
            print(f"addon {name}: {info}")
        for test in tests:
            print(f"[{test.get('status')}] {test.get('addon')} :: {test.get('name')}")
            if test.get("error"):
                print(f"    {test['error']}")
        for err in client_errors:
            print(f"client {err.get('kind')}: {err.get('addon') or ''} {err.get('message')}")
        print(f"restrictions: {run.get('restrictions')}")
        if "report_saved" in result:
            print(f"report saved: {result['report_saved']}")
        if "probe_saved" in result:
            print(f"runtime probe saved: {result['probe_saved']}")
        print(f"{result['passed']} passed, {result['failed']} failed, {len(attributed)} client errors")
    return 1 if failed or attributed else 0


def package(addons: list[pathlib.Path], target: core.Target) -> list[pathlib.Path]:
    import zipfile

    out_dir = core.ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    produced = []
    for addon in addons:
        toc = checks.active_toc(addon)
        version = checks.parse_toc(toc).tags.get("Version", "dev") if toc else "dev"
        archive = out_dir / f"{addon.name}-{version}-forever-{target.interface}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(addon.rglob("*")):
                rel = path.relative_to(addon)
                if path.is_file() and rel.parts[0] != "tests" and not any(p.startswith(".") for p in rel.parts):
                    zf.write(path, pathlib.PurePosixPath(addon.name, *rel.parts).as_posix())
        produced.append(archive)
    return produced
