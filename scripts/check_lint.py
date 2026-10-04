#!/usr/bin/env python3
"""Offline lint: no third-party imports, no network where it does not belong,
no external assets in a page that claims to render offline.

`ruff` is used when it happens to be available, but this script is the check
that always runs -- in CI, on a fresh clone, with no network and no install step.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Modules that may reach the network, and why. Everything else must not.
NETWORK_ALLOWED = {
    "brandkit/measure.py": "the explicit, opt-in --source-url path",
    "brandkit/drafter.py": "the explicit, opt-in openai: drafter hook",
    "scripts/shoot.py": "talks to a headless Chrome on localhost",
}

NETWORK_MODULES = {"urllib", "socket", "http", "requests", "httpx", "ftplib", "smtplib"}

SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def python_files() -> list[Path]:
    return sorted(
        path for path in REPO_ROOT.rglob("*.py")
        if ".git" not in path.parts and "out" not in path.parts
    )


def top_level_imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def check_imports(problems: list[str]) -> int:
    stdlib = set(sys.stdlib_module_names)
    checked = 0
    for path in python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{rel}: does not parse: {exc}")
            continue
        checked += 1
        for name in sorted(top_level_imports(tree)):
            if name in stdlib or name in ("brandkit", "conftest"):
                continue
            if name == "pytest":
                if not rel.startswith("tests/"):
                    problems.append(f"{rel}: pytest may only be imported by tests")
                continue
            problems.append(f"{rel}: third-party import {name!r} (zero-dependency repo)")
        uses_network = any(
            re.search(rf"^(import|from)\s+{module}\b", source, flags=re.M)
            for module in NETWORK_MODULES
        )
        if uses_network and rel not in NETWORK_ALLOWED:
            problems.append(
                f"{rel}: imports a network module but is not on the allow-list "
                f"({', '.join(sorted(NETWORK_ALLOWED))})"
            )
    return checked


def check_offline_pages(problems: list[str]) -> int:
    checked = 0
    for path in sorted(REPO_ROOT.rglob("*.html")):
        if ".git" in path.parts or "out" in path.parts or "img" in path.parts:
            continue
        if not ({"skeletons", "sources"} & set(path.parts)) and path.name != "index.html":
            continue
        text = path.read_text(encoding="utf-8")
        checked += 1
        rel = path.relative_to(REPO_ROOT).as_posix()
        remote = re.findall(r'(?:src|href)\s*=\s*"(?:https?:)?//[^"]+"', text)
        if remote:
            problems.append(f"{rel}: external reference {remote[0]} (pages must render offline)")
        if "@import" in text or re.search(r"url\(\s*['\"]?https?:", text):
            problems.append(f"{rel}: remote CSS asset")
        if re.search(r"<script[^>]*src=", text, flags=re.I):
            problems.append(f"{rel}: remote script")
        if "<script" in text.lower():
            problems.append(f"{rel}: contains a <script> tag; these pages must be static")
        if path.name == "index.html" and re.search(r"@font-face", text):
            problems.append(f"{rel}: @font-face means a font dependency")
    return checked


def check_hygiene(problems: list[str]) -> int:
    checked = 0
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "out" in path.parts:
            continue
        if path.suffix not in (".py", ".md", ".html", ".css", ".csv", ".json", ".yml", ".yaml",
                              ".toml", ".cfg", ".txt"):
            continue
        checked += 1
        rel = path.relative_to(REPO_ROOT).as_posix()
        raw = path.read_bytes()
        if b"\r\n" in raw:
            problems.append(f"{rel}: CRLF line endings")
        text = raw.decode("utf-8", "replace")
        if text and not text.endswith("\n"):
            problems.append(f"{rel}: no trailing newline")
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                problems.append(f"{rel}:{number}: trailing whitespace")
            if "\t" in line and path.suffix in (".py", ".toml"):
                problems.append(f"{rel}:{number}: tab character")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"{rel}: looks like a committed secret ({pattern.pattern})")
    return checked


def check_ruff(problems: list[str]) -> str:
    """Run ruff when it is available; it is never required."""
    from shutil import which

    ruff = which("ruff")
    if not ruff:
        return "ruff: not installed (skipped; the checks above still ran)"
    result = subprocess.run(
        [ruff, "check", str(REPO_ROOT)], capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        problems.append("ruff: " + result.stdout.strip().splitlines()[-1])
    return f"ruff: {'clean' if result.returncode == 0 else 'reported problems'}"


def main() -> int:
    problems: list[str] = []
    py = check_imports(problems)
    html = check_offline_pages(problems)
    files = check_hygiene(problems)
    ruff = check_ruff(problems)

    print(f"lint: {py} python files, {html} html pages, {files} text files checked")
    print(f"lint: {ruff}")
    if problems:
        print(f"\nlint FAILED with {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("lint: clean (no third-party imports, no remote assets, no secrets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
