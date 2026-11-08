"""Create addon repositories from this template and keep their tools current."""
from __future__ import annotations

import pathlib
import shutil

from . import core

MANAGED = ["tools", ".agents", ".claude", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github", ".codex", ".cursor",
           ".vscode", ".gemini", ".gitignore", ".editorconfig", ".luacheckrc", ".luarc.json", ".mcp.json",
           "LICENSE", "waw", "waw.cmd", ".cbmignore", "docs/platform.md", "docs/testing.md", "docs/migration", "docs/guidelines.md"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def _clear_symlinks(source: pathlib.Path, target: pathlib.Path) -> None:
    """Remove destination links that the copy will write again.

    copytree raises FileExistsError for a link that already exists, even with dirs_exist_ok.
    """
    for item in source.rglob("*"):
        if not item.is_symlink():
            continue
        old = target / item.relative_to(source)
        if old.is_symlink():
            old.unlink()


def _copy(name: str, dest: pathlib.Path) -> None:
    source = core.ROOT / name
    target = dest / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        if target.is_symlink():
            target.unlink()
        _clear_symlinks(source, target)
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True, ignore=IGNORE)
    elif source.exists() or source.is_symlink():
        if target.is_symlink() or target.exists():
            target.unlink()
        shutil.copy2(source, target, follow_symlinks=False)


def create(dest: pathlib.Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise core.WawError(f"{dest} exists and is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    for name in MANAGED:
        _copy(name, dest)
    shutil.copy2(core.TARGET_FILE, dest / core.TARGET_FILE.name)
    (dest / "addons").mkdir()
    (dest / "addons" / ".gitkeep").touch()
    (dest / "docs" / "project").mkdir(parents=True)
    (dest / "docs" / "project" / ".gitkeep").touch()
    name = dest.name
    (dest / "README.md").write_text(f"# {name}\n\nThis repository uses the tools of wow-addon-agentic-workflow. See `AGENTS.md`.\n", encoding="utf-8")
    (dest / "PROJECT.md").write_text(
        f"# {name}\n\nThis file holds the facts and rules for this addon. Tool updates do not change it.\n", encoding="utf-8")


# Paths of older tool versions. Version 0.1.0 renamed the tool from "wft" to "waw".
OBSOLETE = ["wft", "wft.cmd", "tools/wft.py", "tools/wftlib", "tools/ingame/WftHarness", "tools/tests/test_wft.py"]
RENAMED_STATE = (".wft", ".waw")


def sync(dest: pathlib.Path) -> list[str]:
    if not (dest / "wow-target.toml").exists():
        raise core.WawError(f"{dest} is not an addon repository")
    for name in MANAGED:
        _copy(name, dest)
    report = list(MANAGED)
    for name in OBSOLETE:
        target = dest / name
        if target.is_symlink() or target.is_file():
            target.unlink()
            report.append(f"removed {name}")
        elif target.is_dir():
            shutil.rmtree(target)
            report.append(f"removed {name}")
    old_state, new_state = (dest / RENAMED_STATE[0]), (dest / RENAMED_STATE[1])
    if old_state.is_dir() and not new_state.exists():
        old_state.rename(new_state)
        report.append(f"renamed {RENAMED_STATE[0]} to {RENAMED_STATE[1]}")
    return report
