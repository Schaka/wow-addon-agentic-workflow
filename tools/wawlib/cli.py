"""The ./waw command line."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import re
import shutil
import sys

from . import __version__, checks, core, docs, graph, mcp_server, runner, snapshot, template


def _print_json(value) -> None:
    print(json.dumps(value, indent=1))


def _resolve_build(value: str | None, target: core.Target) -> int:
    if value in (None, "pinned"):
        return target.build
    if value == "latest":
        builds = snapshot.list_builds(target.product)
        if not builds:
            raise core.WawError("No snapshots. Run: ./waw api sync")
        return builds[-1]
    return int(value)


def cmd_doctor(_args) -> int:
    target = core.load_target()
    problems = 0

    def line(ok: bool | None, label: str, detail: str) -> None:
        print(f"{'ok  ' if ok else 'skip' if ok is None else 'FAIL'} {label}: {detail}")

    line(sys.version_info >= (3, 11), "python", platform.python_version())
    found = runner.find_lua()
    line(bool(found), "lua", found[1] if found else "Install lua5.1 or luajit, or set WAW_LUA.")
    problems += 0 if found else 1
    if found and "PUC" not in found[1]:
        print("     note: LuaJIT runs the tests. waw check rejects LuaJIT-only syntax. CI uses PUC Lua 5.1.")
    line(True if shutil.which("luacheck") else None, "luacheck", shutil.which("luacheck") or "optional, not installed")
    line(True if shutil.which("git") else None, "git", shutil.which("git") or "optional, not installed")
    line(True if graph.available() else None, "code graph", graph.BINARY if graph.available() else "optional, not installed")
    snap = snapshot.path_for(target.product, target.build)
    line(snap.exists(), "api snapshot", f"{snap.name}" if snap.exists() else "Run: ./waw api sync")
    problems += 0 if snap.exists() else 1
    client = None
    try:
        client = core.find_client()
    except core.WawError as exc:
        line(False, "client", str(exc))
    if client:
        line(True, "client", f"{client} ({core.installed_build(client, target.product)})")
    else:
        line(None, "client", "not found. Only the in-client layer needs it.")
    return 1 if problems else 0


def cmd_target_status(args) -> int:
    report = core.status(core.load_target(), offline=args.offline)
    if args.json:
        _print_json(report)
    else:
        t = report["target"]
        print(f"pinned:     {t['version']} interface {t['interface']} (reviewed {t['reviewed']})")
        print(f"live:       {report.get('live_newest') or 'unknown'} {report['live'] or ''}")
        if report["live_error"]:
            print(f"live error: {report['live_error']}")
        head = report["ui_source_head"]
        print(f"ui source:  {head['version'] + ' ' + head['commit'][:10] if head else 'unknown'}")
        print(f"installed:  {report['installed'] or 'not found'}")
        print(f"snapshot:   {report['snapshot']['path']} ({'present' if report['snapshot']['present'] else 'missing'})")
        print(f"drift:      {', '.join(report['drift']) or 'none'}")
    fatal = {"pin-behind-live", "snapshot-missing"}
    return 2 if args.fail_on_drift and fatal & set(report["drift"]) else 0


def cmd_target_bump(args) -> int:
    target = core.load_target()
    build = _resolve_build(args.build, target)
    api = snapshot.Api.load(target.product, build)
    version = api.meta["version"].rsplit(".", 1)[0]
    core.update_target(version=version, build=build, ui_source_commit=api.meta["commit"],
                       reviewed=dt.date.today().isoformat())
    print(f"pinned {version}.{build} ({api.meta['commit'][:10]})")
    print("Run ./waw index to build the shared code graph for this build.")
    return 0


def cmd_api_sync(args) -> int:
    target = core.load_target()
    if args.retail:
        retail = target.raw["retail"]
        meta = snapshot.sync(retail["product"], target.ui_source_repo, retail["ui_source_branch"], None)
    else:
        commit = None if args.latest else target.ui_source_commit
        meta = snapshot.sync(target.product, target.ui_source_repo, target.ui_source_branch, commit)
    print(f"snapshot {meta['product']} {meta['version']} commit {meta['commit'][:10]}, client dump: {meta['dump_source'] or meta['dump_status']}")
    return 0


def _api_for(args) -> snapshot.Api:
    target = core.load_target()
    return snapshot.Api.load(target.product, _resolve_build(getattr(args, "build", None), target))


def cmd_api_lookup(args) -> int:
    server = mcp_server.Server()
    _print_json(server.wow_api_lookup({"name": args.name, "build": _resolve_build(args.build, core.load_target())}))
    return 0


def cmd_api_search(args) -> int:
    _print_json(_api_for(args).search(args.query, args.limit))
    return 0


def cmd_api_restrictions(args) -> int:
    _print_json(_api_for(args).restrictions(args.query, args.limit))
    return 0


def cmd_api_diff(args) -> int:
    server = mcp_server.Server()
    target = core.load_target()
    _print_json(server.wow_api_diff({
        "from_build": _resolve_build(args.old, target), "to_build": _resolve_build(args.new, target),
        "against_retail": args.retail, "summary_only": args.summary}))
    return 0


def run_checks(addons, build, as_json: bool) -> int:
    target = core.load_target()
    api = snapshot.Api.load(target.product, build)
    migrations = checks.load_migrations()
    findings = []
    for addon in addons:
        findings += checks.check_addon(addon, target, api, migrations, addons)
    status, output = checks.run_luacheck(addons)
    errors = [f for f in findings if f.severity == "error"]
    if as_json:
        _print_json({"build": api.meta["version"], "findings": checks.findings_json(findings), "luacheck": status})
    else:
        for f in findings:
            print(f"{f.severity}: {f.file}:{f.line}: [{f.rule}] {f.message}")
        if output and status != "skipped":
            print(output)
        print(f"check: {len(addons)} addons on build {api.meta['build']}, {len(errors)} errors, "
              f"{len(findings) - len(errors)} warnings, luacheck {status}")
    return 1 if errors or status == "failed" else 0


def cmd_check(args) -> int:
    target = core.load_target()
    return run_checks(checks.addon_dirs(args.addons), _resolve_build(args.build, target), args.json)


def cmd_test(args) -> int:
    if args.verbose:
        os.environ["WAW_VERBOSE"] = "1"
    target = core.load_target()
    api = snapshot.Api.load(target.product, _resolve_build(args.build, target))
    return runner.run_offline(api, target, checks.addon_dirs(args.addons), args.filter)


def cmd_verify(args) -> int:
    target = core.load_target()
    build = _resolve_build(args.build, target)
    addons = checks.addon_dirs(args.addons)
    code = run_checks(addons, build, False)
    return runner.run_offline(snapshot.Api.load(target.product, build), target, addons, None) or code


def cmd_link(args) -> int:
    client = core.require_client()
    addons = checks.addon_dirs(args.addons)
    report = runner.unlink_addons(client, addons) if args.remove else runner.link_addons(client, addons, args.copy)
    print("\n".join(report) or "nothing to do")
    return 0


def cmd_ingame_prepare(args) -> int:
    client = core.require_client()
    addons = checks.addon_dirs(args.addons)
    info = runner.prepare_ingame(client, addons, core.load_target(), args.probe)
    print("\n".join(info["links"]))
    print(f"prepared run {info['run_id']} with {info['specs']} spec files")
    print("Ask the user to do this in the client:")
    print("  1. Type /reload (or log in). The tests run and print a WAW result line.")
    print("  2. Type /reload again. This writes the results to disk.")
    print("Then run: ./waw ingame collect --wait 300")
    return 0


def cmd_ingame_collect(args) -> int:
    return runner.collect_ingame(args.wait, args.json)


def cmd_ingame_errors(args) -> int:
    return runner.collect_errors(args.wait, args.json, args.all)


def cmd_package(args) -> int:
    for path in runner.package(checks.addon_dirs(args.addons), core.load_target()):
        print(path.relative_to(core.ROOT))
    return 0


def cmd_new(args) -> int:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.name):
        raise core.WawError("Addon names use letters, digits and underscores, and start with a letter.")
    source = core.ROOT / "tools" / "scaffold" / "ExampleAddon"
    dest = core.ROOT / "addons" / args.name
    if dest.exists():
        raise core.WawError(f"{dest} already exists")
    if not source.is_dir():
        raise core.WawError("tools/scaffold/ExampleAddon is missing")
    shutil.copytree(source, dest)
    for path in list(dest.rglob("*")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("ExampleAddon", args.name), encoding="utf-8")
        if "ExampleAddon" in path.name:
            path.rename(path.with_name(path.name.replace("ExampleAddon", args.name)))
    print(f"created addons/{args.name}")
    return 0


def cmd_index(args) -> int:
    target = core.load_target()
    if args.action == "session-hook":
        return graph.session_hook(target)
    if args.action == "read-hook":
        return graph.read_hook()
    if args.action == "status":
        state = graph.status(target)
        if args.json:
            _print_json(state)
        elif not state["available"]:
            print(state["install"])
        else:
            for entry in state["indexes"]:
                print(f"{'ready  ' if entry['indexed'] else 'missing'} {entry['project']}: {entry['use']}")
        return 0
    if not graph.available():
        print("codebase-memory-mcp is not installed. The code graph is skipped.")
        return 0
    print("\n".join(graph.build(target, args.ref, args.force, args.refresh)))
    return 0


def cmd_new_repo(args) -> int:
    dest = pathlib.Path(args.path).expanduser().resolve()
    template.create(dest)
    print(f"created {dest}")
    print(f"Next: cd {dest} && ./waw api sync && ./waw index && ./waw new MyAddon")
    print("Open a new agent session in that folder. Each session works on one repository.")
    return 0


def cmd_sync_tools(args) -> int:
    dest = pathlib.Path(args.path).expanduser().resolve()
    for line in template.sync(dest):
        print(line if line.startswith(("removed ", "renamed ")) else f"updated {line}")
    return 0


def cmd_docs(_args) -> int:
    hits = docs.scan(core.ROOT)
    for hit in hits:
        print(hit)
    print(f"docs: {len(hits)} Simple English findings")
    return 1 if hits else 0


def cmd_mcp(_args) -> int:
    return mcp_server.serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="waw", description="WoW Forever addon developer tools")
    parser.add_argument("--version", action="version", version=f"waw {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(names, handler, parent=sub, **kw):
        p = parent.add_parser(names, **kw)
        p.set_defaults(handler=handler)
        return p

    def addon_args(p):
        p.add_argument("addons", nargs="*", help="addon folder names. Default: all")

    add("doctor", cmd_doctor, help="make sure that the tools are ready")

    target = add("target", None, help="the pinned game build").add_subparsers(dest="sub", required=True)
    p = add("status", cmd_target_status, target, help="compare pin, live, client and UI source")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fail-on-drift", action="store_true")
    p = add("bump", cmd_target_bump, target, help="pin a synced build after review")
    p.add_argument("--build", default="latest")

    api = add("api", None, help="query the API snapshot").add_subparsers(dest="sub", required=True)
    p = add("sync", cmd_api_sync, api, help="download the UI source and build a snapshot")
    p.add_argument("--latest", action="store_true", help="use the branch head, not the pinned commit")
    p.add_argument("--retail", action="store_true", help="sync the Midnight retail comparison snapshot")
    p = add("lookup", cmd_api_lookup, api)
    p.add_argument("name")
    p.add_argument("--build")
    p = add("search", cmd_api_search, api)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--build")
    p = add("restrictions", cmd_api_restrictions, api)
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--build")
    p = add("diff", cmd_api_diff, api)
    p.add_argument("--from", dest="old", default="pinned")
    p.add_argument("--to", dest="new", default="latest")
    p.add_argument("--retail", action="store_true")
    p.add_argument("--summary", action="store_true")

    p = add("check", cmd_check, help="static checks")
    addon_args(p)
    p.add_argument("--build")
    p.add_argument("--json", action="store_true")
    p = add("test", cmd_test, help="offline Lua tests")
    addon_args(p)
    p.add_argument("--verbose", action="store_true", help="also list the tests that pass")
    p.add_argument("--build")
    p.add_argument("--filter")
    p = add("verify", cmd_verify, help="check, then test")
    addon_args(p)
    p.add_argument("--build")
    p = add("link", cmd_link, help="link addons into the client")
    addon_args(p)
    p.add_argument("--copy", action="store_true")
    p.add_argument("--remove", action="store_true")

    ingame = add("ingame", None, help="test inside the game client").add_subparsers(dest="sub", required=True)
    p = add("prepare", cmd_ingame_prepare, ingame, help="install addons and the harness for one run")
    addon_args(p)
    p.add_argument("--probe", action="store_true", help="also record every API name the client exposes")
    p = add("collect", cmd_ingame_collect, ingame, help="read the results from SavedVariables")
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for results")
    p.add_argument("--json", action="store_true")

    p = add("errors", cmd_ingame_errors, ingame, help="read the Lua errors of the last client session")
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for the next /reload")
    p.add_argument("--all", action="store_true", help="also show errors from other addons")
    p.add_argument("--json", action="store_true")

    p = add("package", cmd_package, help="build release zip files")
    addon_args(p)
    p = add("new", cmd_new, help="create an addon from the example")
    p.add_argument("name")
    p = add("index", cmd_index, help="build or show the code graph indexes")
    p.add_argument("action", nargs="?", default="build", choices=["build", "status", "session-hook", "read-hook"])
    p.add_argument("--ref", action="append", help="also index this optional reference addon")
    p.add_argument("--force", action="store_true", help="index again")
    p.add_argument("--refresh", action="store_true", help="download the reference addons again and index them")
    p.add_argument("--json", action="store_true")
    p = add("new-repo", cmd_new_repo, help="create a new addon repository from this template")
    p.add_argument("path")
    p = add("sync-tools", cmd_sync_tools, help="copy the tools and shared docs of this template to a repository")
    p.add_argument("path")
    add("docs", cmd_docs, help="find Simple English problems in docs and comments")
    add("mcp", cmd_mcp, help="run the MCP server on stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except core.WawError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


