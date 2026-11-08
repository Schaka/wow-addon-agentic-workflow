"""Tests for the waw tool itself. Run them with: python3 tools/tests/test_waw.py"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True

from wawlib import checks, core, graph, lua, mcp_server, runner, snapshot, template  # noqa: E402

FIXTURE = TOOLS / "tests" / "fixtures" / "LegacyAddon"
EXAMPLE = TOOLS / "scaffold" / "ExampleAddon"
TARGET = core.load_target()
HAS_SNAPSHOT = snapshot.path_for(TARGET.product, TARGET.build).exists()


class TemplateSync(unittest.TestCase):
    def test_sync_twice_with_existing_links(self):
        """A second sync must replace a link such as .claude/skills without an error."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "Addon"
            template.create(dest)
            link = dest / ".claude" / "skills"
            self.assertTrue(link.is_symlink())
            template.sync(dest)
            template.sync(dest)
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), "../.agents/skills")

    def test_sync_replaces_wrong_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "Addon"
            template.create(dest)
            link = dest / ".claude" / "skills"
            link.unlink()
            os.symlink("elsewhere", link)
            template.sync(dest)
            self.assertEqual(os.readlink(link), "../.agents/skills")


@unittest.skipUnless(HAS_SNAPSHOT, "run ./waw api sync first")
class SecretGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = snapshot.Api.load(TARGET.product, TARGET.build)

    def findings(self, code, guards=()):
        tokens = lua.tokenize(code)
        return checks._secret_heuristic(tokens, self.api, "x.lua", {}, {}, set(), guards)

    def test_unguarded_value_is_reported(self):
        code = "local hp = UnitHealth('player')\nlocal x = hp + 1\n"
        self.assertEqual(len(self.findings(code)), 1)

    def test_builtin_guard_clears_the_name(self):
        code = "local hp = UnitHealth('player')\nif not issecretvalue(hp) then local x = hp + 1 end\n"
        self.assertEqual(self.findings(code), [])

    def test_configured_helper_clears_the_name(self):
        code = "local hp = UnitHealth('player')\nlocal mx = UnitHealthMax('player')\n" \
               "local f = ArenaLive.Secret.Fraction(hp, mx)\nlocal x = hp + mx\n"
        self.assertEqual(len(self.findings(code)), 2)
        self.assertEqual(self.findings(code, ("Secret.Fraction",)), [])
        self.assertEqual(self.findings(code.replace("ArenaLive.Secret.", "Secret."), ("Secret.Fraction",)), [])

    def test_guard_name_must_match_whole_segments(self):
        code = "local hp = UnitHealth('player')\nlocal f = MySecret.Fraction(hp)\nlocal x = hp + 1\n"
        self.assertEqual(len(self.findings(code, ("Secret.Fraction",))), 1)


@unittest.skipUnless(HAS_SNAPSHOT, "run ./waw api sync first")
class SecretBoolCompare(unittest.TestCase):
    """The rule secret-bool-compare finds field == true on a field of a payload with a Secret flag."""

    @classmethod
    def setUpClass(cls):
        cls.api = snapshot.Api.load(TARGET.product, TARGET.build)

    def findings(self, code, guards=()):
        tokens = lua.tokenize(code)
        found = checks._secret_bool_compare(tokens, self.api, "x.lua", {}, guards)
        return [f for f in found if f.rule == "secret-bool-compare"]

    def test_all_four_forms_are_reported(self):
        for form in ("info.isFullUpdate == true", "info.isFullUpdate == false",
                     "info.isFullUpdate ~= true", "info.isFullUpdate ~= false", "true == info.isFullUpdate"):
            self.assertEqual(len(self.findings(f"if {form} then end\n")), 1, form)

    def test_payload_field_of_unit_aura_is_a_secret_bool(self):
        self.assertIn("isFullUpdate", checks._secret_payload_bool_fields(self.api))

    def test_guard_on_the_line_clears_the_finding(self):
        code = "if not issecretvalue(info.isFullUpdate) and info.isFullUpdate == true then end\n"
        self.assertEqual(self.findings(code), [])

    def test_other_fields_and_locals_are_not_reported(self):
        self.assertEqual(self.findings("if frame.shown == true then end\n"), [])
        self.assertEqual(self.findings("local full = true\nif full == true then end\n"), [])
        self.assertEqual(self.findings("if info.addedAuras == nil then end\n"), [])

    def test_ignore_comment_clears_the_finding(self):
        tokens = lua.tokenize("if info.isFullUpdate == true then end\n")
        found = checks._secret_bool_compare(tokens, self.api, "x.lua", {1: {"secret-bool-compare"}})
        self.assertEqual(found, [])


@unittest.skipUnless(runner.find_lua(), "needs Lua 5.1 or LuaJIT")
class SimulatorSecrets(unittest.TestCase):
    def test_secret_table_and_strict_compare(self):
        """wow.secret_table and the rewrite of name.field == true raise like the client."""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LUA_PATH=f"{runner.LUA_DIR.as_posix()}/?.lua;;")
            proc = subprocess.run([runner.find_lua()[0], str(TOOLS / "tests" / "secret_sim.lua"), tmp],
                                  capture_output=True, text=True, env=env)
        self.assertEqual(proc.stdout.strip(), "ok", proc.stdout + proc.stderr)


class LoadOrder(unittest.TestCase):
    def test_texture_with_file_attribute_is_kept(self):
        """A Texture has a file attribute too. It is a template, not a Script or an Include."""
        with tempfile.TemporaryDirectory() as tmp:
            addon = pathlib.Path(tmp) / "Demo"
            addon.mkdir()
            (addon / "Demo.toc").write_text("## Interface: 16001\n## Title: Demo\nDemo.xml\n", encoding="utf-8")
            (addon / "Demo.xml").write_text(
                '<Ui><Texture name="DemoShield" file="Interface\\RaidFrame\\Shield-Fill" virtual="true"/>'
                '<Script file="Demo.lua"/></Ui>', encoding="utf-8")
            (addon / "Demo.lua").write_text("local x = 1\n", encoding="utf-8")
            items = checks.toc_load_items(addon, TARGET)
        kinds = [(kind, getattr(item, "attrib", {}).get("name", item)) for kind, item in items]
        self.assertEqual(kinds, [("xml", "DemoShield"), ("lua", "Demo.lua")])


class TestRunnerInputs(unittest.TestCase):
    def test_dependencies_join_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name, deps in (("Core", ""), ("Plugin", "## Dependencies: Core\n")):
                (root / name).mkdir()
                (root / name / f"{name}.toc").write_text(f"## Interface: 16001\n## Title: {name}\n{deps}{name}.lua\n")
            old = core.ADDONS_DIR
            core.ADDONS_DIR = root
            try:
                result = runner.with_dependencies([root / "Plugin"])
            finally:
                core.ADDONS_DIR = old
        self.assertEqual([p.name for p in result], ["Plugin", "Core"])

    def test_template_name_in_a_table_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            addon = pathlib.Path(tmp)
            (addon / "a.lua").write_text('local t = { CheckButton = "SomeBlizzardTemplate", x = "NotATemplate" }\n')
            found = runner._lua_template_names([addon], {"SomeBlizzardTemplate"})
        self.assertEqual(found, {"SomeBlizzardTemplate"})


class DocumentationReader(unittest.TestCase):
    def test_file_with_only_tables_is_read(self):
        """Enumerations live in files that have Tables but no Type key."""
        text = ('local UnitAuraShared =\n{\n\tTables =\n\t{\n\t\t{\n\t\t\tName = "UnitAuraSortRule",\n'
                '\t\t\tType = "Enumeration",\n\t\t\tFields =\n\t\t\t{\n'
                '\t\t\t\t{ Name = "Default", Type = "UnitAuraSortRule", EnumValue = 1 },\n\t\t\t},\n\t\t},\n\t},\n};\n')
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "UnitAuraSharedDocumentation.lua").write_text(text, encoding="utf-8")
            _, _, tables, _ = snapshot.read_documentation(pathlib.Path(tmp))
        self.assertEqual(tables["UnitAuraSortRule"]["kind"], "Enumeration")
        self.assertEqual(tables["UnitAuraSortRule"]["fields"][0]["Name"], "Default")


class CodeGraph(unittest.TestCase):
    def test_names_are_stable(self):
        self.assertEqual(graph.framexml_name(TARGET), f"wow-framexml-{TARGET.product}-{TARGET.build}")
        self.assertEqual(graph.repo_name(pathlib.Path("/x/ArenaLive-Forever")), "repo-arenalive-forever")
        self.assertEqual(graph.reference_name("oUF"), "wow-ref-ouf")

    def test_plan_has_all_scopes(self):
        kinds = {entry["kind"] for entry in graph.plan(TARGET)}
        self.assertEqual(kinds, {"this repository", "shared", "shared reference"})

    def test_unwrap_envelope(self):
        wrapped = {"content": [{"type": "text", "text": "{\"a\": 1}"}]}
        self.assertEqual(graph._unwrap(wrapped), {"a": 1})
        self.assertEqual(graph._unwrap({"structuredContent": {"b": 2}}), {"b": 2})


class CaseInsensitiveFiles(unittest.TestCase):
    def test_client_style_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "Sub").mkdir()
            (base / "Sub" / "NamePlates.lua").write_text("", encoding="utf-8")
            self.assertEqual(checks.resolve_case(base, "sub\\Nameplates.lua"), base / "Sub" / "NamePlates.lua")
            self.assertIsNone(checks.resolve_case(base, "Sub/Missing.lua"))


class SyncTools(unittest.TestCase):
    def test_removes_the_old_tool_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "Repo"
            template.create(dest)
            (dest / "wft").write_text("old", encoding="utf-8")
            (dest / "tools" / "wftlib").mkdir()
            (dest / ".wft" / "ingame").mkdir(parents=True)
            report = template.sync(dest)
            self.assertFalse((dest / "wft").exists())
            self.assertFalse((dest / "tools" / "wftlib").exists())
            self.assertTrue((dest / ".waw" / "ingame").is_dir())
            self.assertIn("removed wft", report)


class LuaReader(unittest.TestCase):
    def test_saved_variables(self):
        text = 'DB = {\n["a"] = 1, -- [1]\n["b"] = {"x", "y\\n"},\n[3] = -2.5,\n["c"] = true,\n}\nOther = nil\n'
        data = lua.parse_saved_variables(text)
        self.assertEqual(data["DB"]["a"], 1)
        self.assertEqual(data["DB"]["b"], ["x", "y\n"])
        self.assertEqual(data["DB"][3], -2.5)
        self.assertIsNone(data["Other"])

    def test_never_runs_code(self):
        data = lua.parse_top_level_tables('X = { a = os.execute("rm -rf /"), b = 1 + 2, c = 3 }')
        self.assertEqual(data["X"]["c"], 3)
        self.assertIsInstance(data["X"]["a"], lua.Ref)

    def test_lines_are_counted(self):
        tokens = lua.tokenize("--[[a\nb]]\nlocal x")
        self.assertEqual(tokens[0].line, 3)


@unittest.skipUnless(HAS_SNAPSHOT, "run ./waw api sync first")
class Snapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = snapshot.Api.load(TARGET.product, TARGET.build)

    def test_combat_log_reader_is_not_available(self):
        self.assertEqual(self.api.availability("CombatLogGetCurrentEventInfo")["status"], "absent")
        self.assertEqual(self.api.availability("C_CombatLogSecure.GetCurrentEventInfo")["status"], "secure-only")
        self.assertEqual(self.api.event_status("COMBAT_LOG_EVENT_UNFILTERED")["status"], "restricted")

    def test_every_migration_target_exists(self):
        migrations = checks.load_migrations()
        for old, info in migrations["functions"].items():
            new = info.get("new")
            if new is None:
                continue
            if new.startswith("Settings."):
                self.assertIn("Settings", self.api.ui_globals, old)
            else:
                self.assertEqual(self.api.availability(new)["status"], "available", f"{old} -> {new}")
            self.assertTrue((core.ROOT / info["doc"]).exists(), info["doc"])

    def test_enum_prefix_lookup(self):
        hit = self.api.lookup("Enum.UnitAuraSortRule")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["table"]["kind"], "Enumeration")

    def test_legacy_fixture_findings(self):
        found = checks.check_addon(FIXTURE, TARGET, self.api, checks.load_migrations())
        rules = {f.rule for f in found}
        for rule in ("toc-interface", "toc-file", "migration-event", "api-event", "migration-api",
                     "api-missing", "lua51-syntax", "secret-compare", "secret-bool-compare", "api-global"):
            self.assertIn(rule, rules)
        self.assertFalse([f for f in found if "GetSpellTexture" in f.message], "waw-ignore must suppress a finding")
        self.assertFalse([f for f in found if f.rule == "api-missing" and "string" in f.message])

    def test_example_addon_is_clean(self):
        found = checks.check_addon(EXAMPLE, TARGET, self.api, checks.load_migrations())
        self.assertEqual(found, [])

    def test_mcp_protocol(self):
        server = mcp_server.Server()
        init = server.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(server.handle({"method": "notifications/initialized"}))
        names = {t["name"] for t in server.handle({"id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertIn("wow_target_status", names)
        call = server.handle({"id": 3, "method": "tools/call",
                              "params": {"name": "wow_api_lookup", "arguments": {"name": "C_Spell.GetSpellInfo"}}})
        body = json.loads(call["result"]["content"][0]["text"])
        self.assertEqual(body["availability"]["status"], "available")

    @unittest.skipUnless(runner.find_lua(), "needs Lua 5.1 or LuaJIT")
    def test_harness_round_trip(self):
        """Run the real harness code, parse its output, and read the results."""
        with tempfile.TemporaryDirectory() as tmp:
            client = pathlib.Path(tmp) / "_forever_"
            (client / "Interface" / "AddOns").mkdir(parents=True)
            addons = [EXAMPLE]
            info = runner.prepare_ingame(client, addons, TARGET, probe=True)
            manifest = runner.write_api_manifest(self.api, TARGET, addons)
            saved = client / "WTF" / "Account" / "ACCT" / "SavedVariables"
            saved.mkdir(parents=True)
            binary = runner.find_lua()[0]
            env = dict(os.environ, LUA_PATH=f"{runner.LUA_DIR.as_posix()}/?.lua;;")
            subprocess.run([binary, str(TOOLS / "tests" / "harness_roundtrip.lua"), str(manifest),
                            str(client / "Interface" / "AddOns" / runner.HARNESS), str(saved / f"{runner.HARNESS}.lua")],
                           check=True, cwd=core.ROOT, env=env)
            run = runner._read_run(client, info["run_id"])
            self.assertIsNotNone(run)
            tests = runner._as_list(run["tests"])
            self.assertEqual({t["status"] for t in tests}, {"pass"}, tests)
            self.assertGreater(len(runner._as_list(run["probe_functions"])), 10)
            errors = runner._as_list(run["client_errors"])
            self.assertTrue(any(runner._is_ours(e, ["ExampleAddon"]) for e in errors), errors)
            self.assertFalse(runner._is_ours({"message": "Interface/AddOns/Other/a.lua:1: x"}, ["ExampleAddon"]))
            (core.STATE / "ingame" / "last_run.json").unlink()


if __name__ == "__main__":
    unittest.main(verbosity=1)
