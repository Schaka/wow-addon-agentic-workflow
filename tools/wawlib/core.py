"""Paths, the repository pin, client discovery and build sources."""
from __future__ import annotations

import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET_FILE = ROOT / "wow-target.toml"
LOCAL_FILE = ROOT / "waw.local.toml"
STATE = ROOT / ".waw"
UI_DIR = STATE / "ui-source"


def _cache_root() -> pathlib.Path:
    """Return the data folder that all repositories on this computer share."""
    configured = os.environ.get("WAW_CACHE")
    if configured:
        return pathlib.Path(configured).expanduser()
    if os.name == "nt":
        return pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "waw"
    return pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "waw"


CACHE = _cache_root()
# API snapshots depend only on the build, so all repositories share them.
API_DIR = CACHE / "api"
ADDONS_DIR = ROOT / "addons"
USER_AGENT = "waw-addon-template"
VERSION_URL = "https://{region}.version.battle.net/v2/products/{product}/versions"
INSTALL_SUBDIR = "_forever_"


class WawError(Exception):
    """An expected failure with a message for the user."""


def http_get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


@dataclass
class Target:
    product: str
    game_type: str
    interface: int
    version: str
    build: int
    ui_source_repo: str
    ui_source_branch: str
    ui_source_commit: str
    reviewed: str
    raw: dict = field(default_factory=dict)

    @property
    def full_version(self) -> str:
        return f"{self.version}.{self.build}"


def load_target() -> Target:
    if not TARGET_FILE.exists():
        raise WawError(f"{TARGET_FILE.name} is missing")
    data = tomllib.loads(TARGET_FILE.read_text(encoding="utf-8"))
    t = data["target"]
    return Target(t["product"], t["game_type"], int(t["interface"]), t["version"], int(t["build"]),
                  t["ui_source_repo"], t["ui_source_branch"], t["ui_source_commit"],
                  t.get("reviewed", ""), data)


def update_target(**values) -> None:
    """Rewrite single keys in wow-target.toml and keep its comments."""
    text = TARGET_FILE.read_text(encoding="utf-8")
    for key, val in values.items():
        rendered = f'"{val}"' if isinstance(val, str) else str(val)
        text, count = re.subn(rf"(?m)^({re.escape(key)}\s*=\s*)[^#\n]*?(\s*(#.*)?)$",
                              lambda m, rendered=rendered: m.group(1) + rendered + m.group(2), text, count=1)
        if count != 1:
            raise WawError(f"key {key} not found in {TARGET_FILE.name}")
    TARGET_FILE.write_text(text, encoding="utf-8")


def load_local() -> dict:
    if LOCAL_FILE.exists():
        return tomllib.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    return {}


# --- Game client discovery -------------------------------------------------

def _candidate_roots() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    wow = "World of Warcraft"
    patterns = [
        f"{home}/Faugus/*/drive_c/Program Files (x86)/{wow}",
        f"{home}/Games/*/drive_c/Program Files (x86)/{wow}",
        f"{home}/Games/*/*/drive_c/Program Files (x86)/{wow}",
        f"{home}/.wine/drive_c/Program Files (x86)/{wow}",
        f"{home}/.local/share/lutris/runners/*/drive_c/Program Files (x86)/{wow}",
        f"{home}/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/Program Files (x86)/{wow}",
        f"{home}/.steam/steam/steamapps/compatdata/*/pfx/drive_c/Program Files (x86)/{wow}",
        f"{home}/.var/app/*/data/*/drive_c/Program Files (x86)/{wow}",
        f"C:/Program Files (x86)/{wow}",
        f"C:/Program Files/{wow}",
        f"D:/{wow}",
        f"/Applications/{wow}",
    ]
    found: list[pathlib.Path] = []
    for pattern in patterns:
        found += [pathlib.Path(p) for p in glob.glob(glob.escape(pattern).replace("[*]", "*"))]
    return found


def find_client() -> pathlib.Path | None:
    """Return the `_forever_` directory, or None.

    Order: the WOW_FOREVER_DIR environment variable, waw.local.toml, then the
    usual install locations on Linux, Windows and macOS.
    """
    configured = os.environ.get("WOW_FOREVER_DIR") or load_local().get("client", {}).get("path")
    if configured:
        path = pathlib.Path(configured).expanduser()
        if (path / INSTALL_SUBDIR).is_dir():
            path = path / INSTALL_SUBDIR
        if not path.is_dir():
            raise WawError(f"configured client path does not exist: {path}")
        return path
    for root in _candidate_roots():
        if (root / INSTALL_SUBDIR).is_dir():
            return root / INSTALL_SUBDIR
    return None


def require_client() -> pathlib.Path:
    client = find_client()
    if client is None:
        raise WawError("WoW Forever client not found. Set WOW_FOREVER_DIR or [client] path in waw.local.toml.")
    return client


def installed_build(client: pathlib.Path | None, product: str) -> str | None:
    """Read the installed version from Blizzard's .build.info file."""
    if client is None:
        return None
    info = client.parent / ".build.info"
    if not info.exists():
        return None
    rows = info.read_text(encoding="utf-8", errors="replace").splitlines()
    if not rows:
        return None
    header = [column.split("!")[0] for column in rows[0].split("|")]
    versions = []
    for row in rows[1:]:
        entry = dict(zip(header, row.split("|"), strict=False))
        if entry.get("Product") == product and entry.get("Version"):
            versions.append(entry["Version"])
    return max(versions, key=build_number) if versions else None


def build_number(version: str | int | None) -> int:
    if version is None:
        return 0
    return int(str(version).rsplit(".", 1)[-1])


# --- Remote build sources --------------------------------------------------

def live_versions(product: str, region: str = "us") -> dict:
    """Return {region: version} from Blizzard's public version service."""
    text = http_get(VERSION_URL.format(region=region, product=product)).decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("##")]
    header = [column.split("!")[0] for column in lines[0].split("|")]
    out = {}
    for row in lines[1:]:
        entry = dict(zip(header, row.split("|"), strict=False))
        out[entry["Region"]] = entry["VersionsName"]
    return out


def resolve_branch_head(repo: str, branch: str) -> str:
    if shutil.which("git"):
        proc = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", f"refs/heads/{branch}"],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.split()[0]
    data = json.loads(http_get(f"https://api.github.com/repos/{repo}/commits/{branch}"))
    return data["sha"]


def ui_source_version(repo: str, ref: str) -> str:
    raw = http_get(f"https://raw.githubusercontent.com/{repo}/{ref}/version.txt").decode().strip()
    return raw.split()[0]


def status(target: Target, offline: bool = False) -> dict:
    """Compare the pin with the live build, the local client and the UI source."""
    from . import snapshot

    client = None
    client_error = None
    try:
        client = find_client()
    except WawError as exc:
        client_error = str(exc)
    report: dict = {
        "target": {"product": target.product, "game_type": target.game_type, "interface": target.interface,
                   "version": target.full_version, "ui_source_commit": target.ui_source_commit,
                   "reviewed": target.reviewed},
        "live": None, "ui_source_head": None, "live_error": None,
        "installed": installed_build(client, target.product),
        "client_path": str(client) if client else None, "client_error": client_error,
        "snapshot": None, "drift": [],
    }
    snap = snapshot.path_for(target.product, target.build)
    report["snapshot"] = {"path": str(snap), "present": snap.exists()}
    if not snap.exists():
        report["drift"].append("snapshot-missing")
    if not offline:
        try:
            live = live_versions(target.product)
            report["live"] = live
            newest = max(live.values(), key=build_number)
            report["live_newest"] = newest
            if build_number(newest) > target.build:
                report["drift"].append("pin-behind-live")
            elif build_number(newest) < target.build:
                report["drift"].append("pin-ahead-of-live")
            head = resolve_branch_head(target.ui_source_repo, target.ui_source_branch)
            report["ui_source_head"] = {"commit": head,
                                        "version": ui_source_version(target.ui_source_repo, head)}
            if build_number(report["ui_source_head"]["version"]) < build_number(newest):
                report["drift"].append("ui-source-behind-live")
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
            report["live_error"] = f"{type(exc).__name__}: {exc}"
    if report["installed"]:
        installed = build_number(report["installed"])
        if installed < target.build:
            report["drift"].append("client-behind-pin")
        elif installed > target.build:
            report["drift"].append("client-ahead-of-pin")
    return report
