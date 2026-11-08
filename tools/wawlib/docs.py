"""Find Simple English problems in documents and code comments."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

RULES = [
    (re.compile(r"\b\w+'(t|re|ve|ll|d)\b", re.I), "no contractions"),
    (re.compile(r"\b(should|would|may|might|could)\b", re.I), "use can, will or must"),
    (re.compile(r"\b(has|have|had) been\b", re.I), "use a simple tense"),
    (re.compile(r"—"), "no em-dashes"),
    (re.compile(r";\s"), "no semicolons"),
    (re.compile(r", making\b", re.I), "no -ing verb after a comma"),
    (re.compile(r"\b(verify|verifies|ensure|ensures|validate|validates|confirm|confirms)\b", re.I), "use make sure that"),
    (re.compile(r"\b(config|settings|options)\b"), "use configuration"),
    (re.compile(r"\b(simply|seamlessly|robust|powerful|comprehensive|leverage|crucial)\b|in order to|it is worth noting", re.I), "state the fact"),
    (re.compile(r"\*\*"), "no bold"),
]
SKIP = {".git", ".waw", "dist", "fixtures", "simple-english", "__pycache__", ".lua", ".luarocks", ".install"}
CODE_SPAN = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://\S+")


def _markdown_lines(text: str):
    fenced = False
    in_front_matter = text.startswith("---\n")
    for number, line in enumerate(text.splitlines(), 1):
        if in_front_matter:
            if number > 1 and line.strip() == "---":
                in_front_matter = False
            elif not line.startswith("description:"):
                continue
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            yield number, line


def _comment_lines(path: pathlib.Path, text: str):
    marker = "--" if path.suffix == ".lua" else "#"
    for number, line in enumerate(text.splitlines(), 1):
        at = line.find(marker)
        if at >= 0 and not re.search(r"[\"'][^\"']*$", line[:at]):
            yield number, line[at + len(marker):]


def _candidate_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Prefer the files that git tracks or would track. CI installs Lua tools into the checkout,
    and their third-party comments are not ours to fix."""
    if shutil.which("git"):
        proc = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                              cwd=root, capture_output=True, text=True)
        if proc.returncode == 0:
            return sorted(root / line for line in proc.stdout.splitlines() if line)
    return sorted(root.rglob("*"))


def scan(root: pathlib.Path) -> list[str]:
    hits: list[str] = []
    for path in _candidate_files(root):
        rel = path.relative_to(root)
        if not path.is_file() or set(rel.parts) & SKIP or rel.name == "LICENSE":
            continue
        text_lines = None
        if path.suffix == ".md":
            text_lines = _markdown_lines(path.read_text(encoding="utf-8", errors="replace"))
        elif path.suffix in (".py", ".lua") and rel.name != "docs.py":
            text_lines = _comment_lines(path, path.read_text(encoding="utf-8", errors="replace"))
        if text_lines is None:
            continue
        for number, line in text_lines:
            clean = URL.sub("", CODE_SPAN.sub("", line))
            for regex, advice in RULES:
                if regex.search(clean):
                    hits.append(f"{rel.as_posix()}:{number}: {advice}: {line.strip()[:90]}")
    return hits
