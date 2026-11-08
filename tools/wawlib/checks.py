"""Static checks that run without a game client."""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from . import core, lua
from .snapshot import Api

DATA = pathlib.Path(__file__).parent / "data"
IGNORE_RE = re.compile(r"--\s*waw-ignore:\s*([\w,\- ]+)")
TOC_SUFFIX_RE = re.compile(r"[-_](Mainline|Standard|Camelot|Forever|Classic|Vanilla|TBC|BCC|Wrath|WOTLKC|Cata|Mists)$", re.I)
LUA_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in", "local",
                "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}
FORBIDDEN_GLOBALS = {"require", "dofile", "loadfile", "module", "io", "os", "package"}
ARITH_OR_COMPARE = {"+", "-", "*", "/", "%", "^", "<", ">", "<=", ">=", "==", "~="}
SKIP_DIRS = {"tests", "Libs", "libs"}
LUA_BASE = {"assert", "error", "getmetatable", "ipairs", "next", "pairs", "pcall", "print", "rawequal", "rawget",
            "rawset", "select", "setmetatable", "tonumber", "tostring", "type", "unpack", "xpcall"}


@dataclass
class Finding:
    severity: str  # error | warning
    rule: str
    file: str
    line: int
    message: str


def load_migrations() -> dict:
    return json.loads((DATA / "migrations.json").read_text(encoding="utf-8"))


# --- TOC and XML ------------------------------------------------------------

@dataclass
class Toc:
    path: pathlib.Path
    tags: dict
    files: list  # (relative name, line number)


CONDITION_RE = re.compile(r"\s*\[(\w+)\s*([^\]]*)\]")


def parse_toc(path: pathlib.Path) -> Toc:
    tags: dict = {}
    files: list = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("##"):
            key, sep, value = line[2:].partition(":")
            if sep:
                tags[key.strip()] = value.strip()
        elif line and not line.startswith("#"):
            files.append((line, number))
    return Toc(path, tags, files)


def toc_entry_applies(entry: str, game_type: str) -> tuple[str, bool]:
    """Strip load conditions from a TOC file line and evaluate them."""
    conditions = CONDITION_RE.findall(entry)
    name = CONDITION_RE.sub("", entry).strip()
    aliases = {game_type, "forever", "camelot", "mainline"}
    for key, value in conditions:
        listed = {v.strip().lower() for v in value.split(",") if v.strip()}
        if key == "AllowLoadGameType" and listed and not listed & aliases:
            return name, False
        if key == "ExcludeLoadGameType" and listed & aliases:
            return name, False
    name = name.replace("[Family]", "Mainline").replace("[Game]", "Camelot")
    return name.replace("\\", "/"), True


def find_tocs(addon: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in addon.glob("*.toc") if p.is_file())


def active_toc(addon: pathlib.Path) -> pathlib.Path | None:
    """Pick the TOC the Forever client loads: a game-type suffix wins."""
    tocs = {p.stem: p for p in find_tocs(addon)}
    for suffix in ("_Camelot", "-Camelot", "_Forever", "-Forever", "_Mainline", "-Mainline", ""):
        hit = tocs.get(addon.name + suffix)
        if hit:
            return hit
    return None


def _exact_case_exists(base: pathlib.Path, relative: str) -> tuple[bool, bool]:
    """Return (exists on this file system, the case matches exactly)."""
    current = base
    case_ok = True
    for part in relative.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        if not current.is_dir():
            return False, False
        names = {p.name: p.name for p in current.iterdir()}
        if part in names:
            current = current / part
            continue
        fold = {n.lower(): n for n in names}
        if part.lower() in fold:
            case_ok = False
            current = current / fold[part.lower()]
            continue
        return False, False
    return True, case_ok


def check_toc(addon: pathlib.Path, target: core.Target) -> list[Finding]:
    findings: list[Finding] = []
    rel = lambda p: p.relative_to(core.ROOT).as_posix()  # noqa: E731
    tocs = find_tocs(addon)
    stems = {p.stem for p in tocs}
    if not tocs:
        return [Finding("error", "toc-missing", rel(addon), 0, "The addon has no .toc file.")]
    if active_toc(addon) is None:
        findings.append(Finding("error", "toc-name", rel(addon), 0,
                                f"No TOC named {addon.name}.toc or {addon.name}_Camelot.toc."))
    if f"{addon.name}_Forever" in stems and f"{addon.name}_Camelot" not in stems:
        findings.append(Finding("warning", "toc-forever-suffix", rel(addon), 0,
                                "BigWigs packager recognizes the _Camelot suffix but not _Forever. Prefer _Camelot.toc."))
    for path in tocs:
        toc = parse_toc(path)
        match = TOC_SUFFIX_RE.search(path.stem)
        applies = match is None or match.group(1).lower() in ("camelot", "forever", "mainline")
        interfaces = {v.strip() for v in toc.tags.get("Interface", "").split(",") if v.strip()}
        if not interfaces:
            findings.append(Finding("error", "toc-interface", rel(path), 1, "The ## Interface line is missing."))
        elif applies and str(target.interface) not in interfaces:
            findings.append(Finding("error", "toc-interface", rel(path), 1,
                                    f"## Interface must include {target.interface}, the pinned value. Found: {sorted(interfaces)}."))
        for tag in ("Title",):
            if tag not in toc.tags:
                findings.append(Finding("warning", "toc-tag", rel(path), 1, f"The ## {tag} line is missing."))
        if not applies:
            continue
        for entry, number in toc.files:
            name, active = toc_entry_applies(entry, target.game_type)
            if not active:
                continue
            exists, case_ok = _exact_case_exists(path.parent, name)
            if not exists:
                findings.append(Finding("error", "toc-file", rel(path), number, f"The listed file does not exist: {name}"))
            elif not case_ok:
                findings.append(Finding("warning", "toc-file-case", rel(path), number,
                                        f"The file name case differs on disk: {name}. Case matters on Linux tools."))
    return findings


def _attr(node: ET.Element, name: str) -> str | None:
    """Read an XML attribute. The client ignores the case of attribute names."""
    for key, value in node.attrib.items():
        if key.lower() == name:
            return value
    return None


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def resolve_case(base: pathlib.Path, relative: str) -> pathlib.Path | None:
    """Find a file the way the client does. The client ignores letter case in file names."""
    current = base
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        if not current.is_dir():
            return None
        exact = current / part
        if exact.exists():
            current = exact
            continue
        match = next((child for child in current.iterdir() if child.name.lower() == part.lower()), None)
        if match is None:
            return None
        current = match
    return current


def check_xml(path: pathlib.Path) -> list[Finding]:
    rel = path.relative_to(core.ROOT).as_posix()
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [Finding("error", "xml-parse", rel, exc.position[0], f"XML parse error: {exc}")]
    findings = []
    for node in root.iter():
        tag = _tag(node)
        ref = _attr(node, "file")
        if tag in ("Script", "Include") and ref:
            exists, case_ok = _exact_case_exists(path.parent, ref.replace("\\", "/"))
            if not exists:
                findings.append(Finding("error", "xml-file", rel, 0, f"<{tag} file> target does not exist: {ref}"))
            elif not case_ok:
                findings.append(Finding("warning", "xml-file-case", rel, 0,
                                        f"<{tag} file> {ref} differs in letter case from the file on disk. "
                                        "The client accepts it. Linux tools and packagers can miss the file."))
    return findings


def toc_load_items(addon: pathlib.Path, target: core.Target) -> list[tuple[str, object]]:
    """Return ("lua", relative path) and ("xml", element) items in client load order."""
    toc_path = active_toc(addon)
    if toc_path is None:
        return []
    items: list[tuple[str, object]] = []

    def visit_xml(path: pathlib.Path) -> None:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return
        for node in root:
            tag = _tag(node)
            # Only Script and Include use file as a path. A Texture has file="Interface\\..." too.
            ref = _attr(node, "file") if tag in ("Script", "Include") else None
            if ref:
                ref_path = resolve_case(path.parent, ref)
                if ref_path is None:
                    continue
                if tag == "Include" and ref_path.suffix.lower() == ".xml":
                    visit_xml(ref_path)
                else:
                    items.append(("lua", ref_path.relative_to(addon).as_posix()))
            elif tag == "Script":
                continue
            else:
                items.append(("xml", node))

    for entry, _ in parse_toc(toc_path).files:
        name, active = toc_entry_applies(entry, target.game_type)
        if not active:
            continue
        path = resolve_case(addon, name)
        if path is None:
            continue
        if name.lower().endswith(".xml"):
            visit_xml(path)
        elif name.lower().endswith(".lua"):
            items.append(("lua", path.relative_to(addon).as_posix()))
    return items


def toc_dependencies(addon: pathlib.Path) -> list[str]:
    toc_path = active_toc(addon)
    if toc_path is None:
        return []
    tags = parse_toc(toc_path).tags
    out: list[str] = []
    for key in ("Dependencies", "RequiredDeps", "Dep"):
        out += [v.strip() for v in tags.get(key, "").split(",") if v.strip()]
    return out


def addon_templates(addon: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for path in addon.rglob("*.xml"):
        try:
            for node in ET.parse(path).getroot().iter():
                if (_attr(node, "virtual") or "").lower() == "true" and _attr(node, "name"):
                    names.add(_attr(node, "name"))
        except ET.ParseError:
            pass
    return names


def xml_frame_names(addon: pathlib.Path) -> set[str]:
    """Collect the global names of frames and regions that the XML files of an addon create.

    A name can start with $parent. The client replaces it with the name of the closest named ancestor.
    A name from a virtual template that holds $parent stays unresolved, because the template user decides it.
    """
    names: set[str] = set()

    def walk(node: ET.Element, parent_name: str) -> None:
        name = _attr(node, "name")
        resolved = parent_name
        if name:
            if "$parent" in name:
                if parent_name:
                    resolved = name.replace("$parent", parent_name)
                    names.add(resolved)
            else:
                resolved = name
                names.add(name)
        for child in node:
            walk(child, resolved)

    for path in addon.rglob("*.xml"):
        try:
            walk(ET.parse(path).getroot(), "")
        except ET.ParseError:
            pass
    return names


# Names that are always valid and that the snapshot does not list as globals.
ALWAYS_KNOWN_GLOBALS = {"_G", "_VERSION", "Enum", "self", "arg"}


CREATE_FRAME_TEMPLATE_RE = re.compile(r"""CreateFrame\s*\(\s*["'][^"']+["']\s*,[^,)]*,[^,)]*,\s*["']([^"']+)["']""")


def check_templates(addon: pathlib.Path, all_addons: list[pathlib.Path], api: Api) -> list[Finding]:
    """Report inherited templates that neither the addons nor the client define."""
    known = set(api.data.get("ui_templates", {})) | {"NOT_SYNCED"}
    if len(known) == 1:
        return []
    for other in all_addons:
        known |= addon_templates(other)
    findings: list[Finding] = []

    def report(rel: str, line: int, names: str) -> None:
        for name in (n.strip() for n in names.split(",")):
            if name and name not in known and "$" not in name:
                findings.append(Finding("error", "api-template", rel, line,
                                        f"The template {name} does not exist on build {api.meta['build']}."))

    for path in _source_files(addon, ".xml"):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        rel = path.relative_to(core.ROOT).as_posix()
        for node in root.iter():
            if _attr(node, "inherits"):
                report(rel, 0, _attr(node, "inherits"))
    for path in _source_files(addon, ".lua"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CREATE_FRAME_TEMPLATE_RE.finditer(text):
            report(path.relative_to(core.ROOT).as_posix(), text.count("\n", 0, match.start()) + 1, match.group(1))
    return findings


# --- Lua source -------------------------------------------------------------

def _collect_declared(tokens: list[lua.Token]) -> set[str]:
    """Collect the names that the addon defines. One flat set gives few false errors."""
    declared: set[str] = set()
    for i, tok in enumerate(tokens):
        if tok.kind != "name":
            continue
        following = tokens[i + 1] if i + 1 < len(tokens) else tok
        previous = tokens[i - 1] if i else None
        if tok.value == "local":
            j = i + 1
            if tokens[j].value == "function":
                declared.add(tokens[j + 1].value)
                continue
            while tokens[j].kind == "name":
                declared.add(tokens[j].value)
                if tokens[j + 1].value == ",":
                    j += 2
                else:
                    break
        elif tok.value == "for":
            j = i + 1
            while tokens[j].kind == "name" and tokens[j].value != "in":
                declared.add(tokens[j].value)
                if tokens[j + 1].value == ",":
                    j += 2
                else:
                    break
        elif tok.value == "function":
            j = i + 1
            if tokens[j].kind == "name" and tokens[j + 1].value == "(":
                declared.add(tokens[j].value)
            while tokens[j].value != "(" and tokens[j].kind != "eof":
                j += 1
            j += 1
            while tokens[j].value != ")" and tokens[j].kind != "eof":
                if tokens[j].kind == "name":
                    declared.add(tokens[j].value)
                j += 1
        elif following.kind == "op" and following.value == "=" and (previous is None or previous.value not in (".", ":", "{", ",")):
            declared.add(tok.value)
    return declared


def _dotted_at(tokens: list[lua.Token], i: int) -> str:
    parts = [tokens[i].value]
    j = i + 1
    while tokens[j].value == "." and tokens[j].kind == "op" and tokens[j + 1].kind == "name":
        parts.append(tokens[j + 1].value)
        j += 2
    return ".".join(parts)


def scan_lua(path: pathlib.Path, api: Api, migrations: dict, declared: set[str],
             known_extra: set[str] | None = None) -> list[Finding]:
    rel = path.relative_to(core.ROOT).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tokens = lua.tokenize(text)
    except lua.LuaSyntaxError as exc:
        return [Finding("error", "lua-syntax", rel, 0, str(exc))]
    ignores: dict[int, set[str]] = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = IGNORE_RE.search(line)
        if match:
            rules = {r.strip() for r in re.split(r"[, ]+", match.group(1)) if r.strip()}
            ignores.setdefault(number, set()).update(rules)
            ignores.setdefault(number + 1, set()).update(rules)

    findings: list[Finding] = []

    def add(severity: str, rule: str, line: int, message: str) -> None:
        if rule not in ignores.get(line, set()):
            findings.append(Finding(severity, rule, rel, line, message))

    functions_map = migrations["functions"]
    events_map = migrations["events"]
    custom_prefixes = tuple(core.load_target().raw.get("checks", {}).get("custom_event_prefixes", []))
    optional_globals = set(core.load_target().raw.get("checks", {}).get("optional_globals", []))
    generated_prefixes = tuple(core.load_target().raw.get("checks", {}).get("generated_global_prefixes", []))
    known_globals = (api.ui_globals | api.dump_globals | api.dump_lua | set(api.tables) | api.namespaces
                     | {n.split(".")[0] for n in api.functions} | set(api.cvars) | ALWAYS_KNOWN_GLOBALS
                     | optional_globals | (known_extra or set()))
    secret_locals: dict[str, str] = {}
    guarded: set[str] = set()

    for i, tok in enumerate(tokens):
        previous = tokens[i - 1] if i else lua.Token("eof", "", 0)
        following = tokens[i + 1] if tok.kind != "eof" else tok

        if tok.kind == "name" and tok.value == "goto":
            add("error", "lua51-syntax", tok.line, "goto is Lua 5.2 syntax. WoW runs Lua 5.1. LuaJIT accepts it, so tests alone do not find this.")
        if tok.kind == "op" and tok.value == "::":
            add("error", "lua51-syntax", tok.line, "Labels (::name::) do not exist in Lua 5.1.")
        if tok.kind == "op" and tok.value == "//":
            add("error", "lua51-syntax", tok.line, "The operator // does not exist in Lua 5.1. Use math.floor(a / b).")
        if tok.kind == "op" and tok.value in ("<<", ">>", "&", "|"):
            add("error", "lua51-syntax", tok.line, f"The operator {tok.value} does not exist in Lua 5.1. Use the bit library.")
        if tok.kind == "op" and tok.value == "~" and following.value != "=":
            add("error", "lua51-syntax", tok.line, "The operator ~ does not exist in Lua 5.1. Use bit.bxor or bit.bnot.")

        # Event registration.
        if tok.kind == "name" and tok.value in ("RegisterEvent", "RegisterUnitEvent") and following.value == "(" \
                and tokens[i + 2].kind == "string":
            event, line = tokens[i + 2].value, tokens[i + 2].line
            base_event = next((name for name in events_map if event.startswith(name + "_")), None)
            if custom_prefixes and event.startswith(custom_prefixes):
                pass
            elif event in events_map or base_event:
                info = events_map[event if event in events_map else base_event]
                add("error", "migration-event", line, f"{event}: {info['note']} See {info['doc']}.")
            else:
                state = api.event_status(event)
                if state["status"] == "absent":
                    add("error", "api-event", line, f"The event {event} does not exist on build {api.meta['build']}.")
                elif state["status"] == "restricted":
                    add("error", "api-event-restricted", line, f"The event {event} has HasRestrictions on build {api.meta['build']}. Addon registration can be blocked.")

        if tok.kind != "name" or tok.value in LUA_KEYWORDS or previous.value in (".", ":") and previous.kind == "op":
            continue

        name = _dotted_at(tokens, i)
        head = name.split(".")[0]
        if head in FORBIDDEN_GLOBALS and head not in declared:
            add("error", "lua-sandbox", tok.line, f"{head} is not available in the WoW Lua sandbox.")
            continue
        if head in declared:
            continue

        if head in LUA_BASE:
            continue
        # A table or namespace that nothing defines: the client reads it as nil and the next index raises an error.
        # Only a read like Name[...] or Name.field counts. A call is checked below. An empty snapshot checks nothing.
        if tokens[i + 1].kind == "op" and tokens[i + 1].value in ("[", ".") and head not in known_globals \
                and api.ui_globals and not head.startswith("C_") \
                and not (generated_prefixes and head.startswith(generated_prefixes)):
            add("warning", "api-global", tok.line,
                f"{head} is not defined by the addons or by build {api.meta['build']}. The client reads it as nil. "
                "If an optional addon defines it, add it to optional_globals in wow-target.toml.")
            continue
        is_call = "." not in name and tokens[i + 1].value == "("
        candidates = [name] if "." in name and name.startswith("C_") else [head]
        for candidate in candidates:
            if candidate in functions_map:
                info = functions_map[candidate]
                replacement = f" Replace it with {info['new']}." if info.get("new") else ""
                add(info.get("severity", "error"), "migration-api", tok.line,
                    f"{candidate}: {info['note']}{replacement} See {info['doc']}.")
                break
            if head.startswith("C_") and "." in name:
                state = api.availability(name.split(".")[0] + "." + name.split(".")[1])
                if head not in api.namespaces:
                    add("error", "api-namespace", tok.line, f"The namespace {head} does not exist on build {api.meta['build']}.")
                elif state["status"] == "absent":
                    add("error", "api-missing", tok.line, f"{name} does not exist on build {api.meta['build']}.")
                elif state["status"] == "secure-only":
                    add("error", "api-secure-only", tok.line, f"{name} is SecureOnly. Addon code cannot call it.")
                elif state["status"] == "deprecated-shim":
                    add("warning", "api-deprecated", tok.line, f"{name} exists only as a Blizzard deprecation shim. Replace it with {state['shim']['new']}.")
                break
            if is_call:
                state = api.availability(candidate)
                if state["status"] == "absent":
                    add("error", "api-missing", tok.line, f"{candidate} does not exist on build {api.meta['build']}.")
                elif state["status"] == "secure-only":
                    add("error", "api-secure-only", tok.line, f"{candidate} is SecureOnly. Addon code cannot call it.")
                elif state["status"] == "deprecated-shim":
                    add("warning", "api-deprecated", tok.line, f"{candidate} exists only as a Blizzard deprecation shim."
                        + (f" Replace it with {state['shim']['new']}." if state["shim"]["new"] else ""))

    guards = tuple(core.load_target().raw.get("checks", {}).get("secret_guards", []))
    findings.extend(_secret_heuristic(tokens, api, rel, ignores, secret_locals, guarded, guards))
    findings.extend(_secret_bool_compare(tokens, api, rel, ignores, guards))
    return findings


def _secret_api_names(api: Api) -> set[str]:
    names = set()
    for name, entry in api.functions.items():
        flags = entry["flags"]
        if flags.get("SecretReturns") or any(k.startswith(("SecretWhen", "ConditionalSecret")) for k in flags):
            names.add(name)
    return names


def _call_end(tokens: list[lua.Token], open_index: int) -> int:
    depth = 0
    for j in range(open_index, len(tokens)):
        if tokens[j].kind == "op" and tokens[j].value == "(":
            depth += 1
        elif tokens[j].kind == "op" and tokens[j].value == ")":
            depth -= 1
            if depth == 0:
                return j
    return len(tokens) - 1


def _guard_matches(name: str, guards: tuple) -> bool:
    """A configured guard matches a call name that equals it or ends with it after a dot."""
    return any(name == g or name.endswith("." + g) for g in guards)


def _guarded_names(tokens: list[lua.Token], guards: tuple) -> set[str]:
    """Collect the names that are direct arguments of a guard call.

    The built-in guards are issecretvalue and canaccessvalue. The configuration key
    [checks] secret_guards adds the names of an addon's own helper functions.
    """
    names: set[str] = set()
    all_guards = ("issecretvalue", "canaccessvalue") + tuple(guards)
    for i, tok in enumerate(tokens):
        if tok.kind != "name" or (i and tokens[i - 1].value in (".", ":") and tokens[i - 1].kind == "op"):
            continue
        dotted = _dotted_at(tokens, i)
        call_at = i + 1 + 2 * dotted.count(".")
        if not _guard_matches(dotted, all_guards) or tokens[call_at].value != "(":
            continue
        end = _call_end(tokens, call_at)
        depth = 0
        for j in range(call_at, end + 1):
            value = tokens[j].value
            if tokens[j].kind == "op" and value in ("(", "{", "["):
                depth += 1
            elif tokens[j].kind == "op" and value in (")", "}", "]"):
                depth -= 1
            elif depth == 1 and tokens[j].kind == "name" and tokens[j - 1].value in ("(", ",") \
                    and tokens[j + 1].value in (",", ")"):
                names.add(value)
    return names


def _secret_heuristic(tokens, api, rel, ignores, secret_locals, guarded, guards=()) -> list[Finding]:
    """Warn when a secret-capable return value reaches an operator unguarded.

    This is a heuristic. It follows one local variable per assignment. The
    in-client layer remains the authority.
    """
    secret_apis = _secret_api_names(api)
    out: list[Finding] = []
    text_guard = _guarded_names(tokens, guards)

    def report(line: int, what: str) -> None:
        if "secret-compare" not in ignores.get(line, set()):
            out.append(Finding("warning", "secret-compare", rel, line,
                               f"{what} can be a secret value. Arithmetic and comparison raise an error for addons. Guard it with issecretvalue, or pass it directly to a widget."))

    for i, tok in enumerate(tokens):
        if tok.kind != "name":
            continue
        name = _dotted_at(tokens, i)
        call_at = i + 1 + 2 * name.count(".")
        if name in secret_apis and tokens[call_at].value == "(" and not (i and tokens[i - 1].value in (".", ":")):
            end = _call_end(tokens, call_at)
            before = tokens[i - 1].value if i and tokens[i - 1].kind == "op" else ""
            after = tokens[end + 1].value if tokens[end + 1].kind == "op" else ""
            if before in ARITH_OR_COMPARE or after in ARITH_OR_COMPARE:
                report(tok.line, f"The return value of {name}")
            if i >= 3 and tokens[i - 1].value == "=" and tokens[i - 2].kind == "name" and tokens[i - 3].value == "local":
                secret_locals[tokens[i - 2].value] = name
        elif tok.value in secret_locals and tok.value not in text_guard:
            before = tokens[i - 1]
            after = tokens[i + 1]
            if (before.kind == "op" and before.value in ARITH_OR_COMPARE and before.value != "=") or \
                    (after.kind == "op" and after.value in ARITH_OR_COMPARE):
                report(tok.line, f"{tok.value} (from {secret_locals[tok.value]})")
    return out


def _has_secret_flag(flags: dict) -> bool:
    """True for a Secret* flag that can hide a returned or delivered value. SecretArguments only limits arguments."""
    return any((k.startswith("Secret") and k != "SecretArguments") or k.startswith("ConditionalSecret") for k in flags)


def _bool_fields(api: Api, type_name: str | None, seen: set[str] | None = None, depth: int = 0) -> set[str]:
    """Names of the boolean fields of a documented structure, including nested structures."""
    seen = seen if seen is not None else set()
    table = api.tables.get(type_name or "")
    if not table or table.get("kind") != "Structure" or type_name in seen or depth > 3:
        return set()
    seen.add(type_name)
    names: set[str] = set()
    for field in table.get("fields", []):
        if field.get("Type") == "bool":
            names.add(field["Name"])
        else:
            for nested in (field.get("Type"), field.get("InnerType")):
                names |= _bool_fields(api, nested, seen, depth + 1)
    return names


def _secret_payload_bool_fields(api: Api) -> set[str]:
    """Boolean fields in the payload tables of events that have a Secret* flag. UNIT_AURA gives isFullUpdate."""
    cached = getattr(api, "_secret_payload_bools", None)
    if cached is None:
        cached = set()
        for entry in api.events.values():
            if _has_secret_flag(entry.get("flags", {})):
                for item in entry.get("payload") or []:
                    for type_name in (item.get("Type"), item.get("InnerType")):
                        cached |= _bool_fields(api, type_name)
        api._secret_payload_bools = cached
    return cached


def _secret_result_bool_fields(api: Api, function_name: str) -> set[str]:
    """Boolean fields of the structures that a function with a Secret* flag returns."""
    entry = api.functions.get(function_name)
    if not entry or not _has_secret_flag(entry.get("flags", {})):
        return set()
    names: set[str] = set()
    for item in entry.get("returns") or []:
        for type_name in (item.get("Type"), item.get("InnerType")):
            names |= _bool_fields(api, type_name)
    return names


BOOL_LITERALS = ("true", "false")
COMPARE_OPS = ("==", "~=")
GUARD_WORDS = ("issecretvalue", "canaccessvalue", "issecrettable", "canaccesstable")


def _secret_bool_compare(tokens: list[lua.Token], api: Api, rel: str, ignores: dict, guards: tuple = ()) -> list[Finding]:
    """Warn for field == true, field == false, field ~= true and field ~= false on a field that can be a secret boolean.

    A secret boolean raises an error in a comparison, but the simulator cannot show this, because Lua never
    calls __eq for a userdata compared with a boolean. The rule needs a field access (name.field). It uses these names:
    the boolean fields of the payload of every event with a Secret* flag, and the boolean fields of the result
    of every function with a Secret* flag that the same file calls. A line with a guard call is skipped.
    """
    names = set(_secret_payload_bool_fields(api))
    called = {_dotted_at(tokens, i) for i, tok in enumerate(tokens)
              if tok.kind == "name" and i + 1 < len(tokens) and tokens[i + 1].value == "("
              and not (i and tokens[i - 1].value in (".", ":") and tokens[i - 1].kind == "op")}
    for function_name in called:
        names |= _secret_result_bool_fields(api, function_name)
    if not names:
        return []

    guard_lines = {tok.line for tok in tokens
                   if tok.kind == "name" and (tok.value in GUARD_WORDS or _guard_matches(tok.value, guards))}
    out: list[Finding] = []
    for i, tok in enumerate(tokens):
        if tok.kind != "op" or tok.value not in COMPARE_OPS or i < 1 or i + 1 >= len(tokens):
            continue
        left, right = tokens[i - 1], tokens[i + 1]
        field = None
        if right.kind == "name" and right.value in BOOL_LITERALS and left.kind == "name" and i >= 2 \
                and tokens[i - 2].kind == "op" and tokens[i - 2].value == ".":
            field = left
        elif left.kind == "name" and left.value in BOOL_LITERALS and right.kind == "name" \
                and i + 3 < len(tokens) and tokens[i + 2].value == "." and tokens[i + 3].kind == "name":
            field = tokens[i + 3]
        # A call such as x.isFullUpdate() or a longer chain after the field is not a plain field read.
        if field is None or field.value not in names:
            continue
        if field.line in guard_lines or "secret-bool-compare" in ignores.get(tok.line, set()):
            continue
        out.append(Finding("warning", "secret-bool-compare", rel, tok.line,
                           f"The field {field.value} can be a secret boolean. A comparison with {'true' if 'true' in (left.value, right.value) else 'false'} "
                           "raises an error in the client, but the simulator does not show it. "
                           "Test it with issecretvalue first, or use a helper such as Secret.IsTrue."))
    return out


def addon_dirs(names: list[str] | None = None) -> list[pathlib.Path]:
    if not core.ADDONS_DIR.is_dir():
        return []
    dirs = sorted(p for p in core.ADDONS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))
    if names:
        wanted = set(names)
        missing = wanted - {p.name for p in dirs}
        if missing:
            raise core.WawError(f"Unknown addon: {', '.join(sorted(missing))}")
        dirs = [p for p in dirs if p.name in wanted]
    return dirs


def _source_files(addon: pathlib.Path, suffix: str) -> list[pathlib.Path]:
    out = []
    for path in addon.rglob(f"*{suffix}"):
        if not set(path.relative_to(addon).parts[:-1]) & SKIP_DIRS:
            out.append(path)
    return sorted(out)


def check_addon(addon: pathlib.Path, target: core.Target, api: Api, migrations: dict,
                all_addons: list[pathlib.Path] | None = None) -> list[Finding]:
    findings = check_toc(addon, target)
    findings += check_templates(addon, all_addons or [addon], api)
    for path in _source_files(addon, ".xml"):
        findings += check_xml(path)
    lua_files = _source_files(addon, ".lua")
    declared: set[str] = set(target.raw.get("checks", {}).get("extra_globals", []))
    for path in sorted(addon.rglob("*.lua")):
        if "tests" in path.relative_to(addon).parts:
            continue
        try:
            declared |= _collect_declared(lua.tokenize(path.read_text(encoding="utf-8", errors="replace")))
        except lua.LuaSyntaxError:
            pass
    xml_names: set[str] = set()
    for other in (all_addons or [addon]):
        xml_names |= xml_frame_names(other)
    for path in lua_files:
        findings += scan_lua(path, api, migrations, declared, xml_names)
    return findings


def run_luacheck(addons: list[pathlib.Path]) -> tuple[str, str]:
    """Return (status, output). Status is ok, failed or skipped."""
    binary = shutil.which("luacheck")
    if binary is None or not addons:
        return "skipped", "luacheck is not installed."
    proc = subprocess.run([binary, "-q", "--no-color", "--exclude-files", "**/Libs/**", "--", *map(str, addons)],
                          capture_output=True, text=True, cwd=core.ROOT)
    return ("ok" if proc.returncode == 0 else "failed"), proc.stdout.strip()


def findings_json(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]
