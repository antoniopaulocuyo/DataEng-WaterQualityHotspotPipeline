"""Check that every file the README points to exists.

Looks at markdown links `[text](path)` and `` `path` `` references that start with a repo folder
(docs/, src/, config/, sql/, scripts/, tests/, dags/). URLs and anchors are ignored; data/ and outputs/ are
skipped because they are created by a run and are git-ignored.

Run from the repository root:
    python scripts/check_readme.py [README.md]                                    (exit code 1 if anything is missing)
In Docker the README and the top-level files are not mounted, so mount the whole repository for this one run:
    docker compose run --rm -T -v "${PWD}:/opt/project" pipeline python scripts/check_readme.py       (PowerShell)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")
TICK = re.compile(r"`((?:docs|src|config|sql|scripts|tests|dags)/[A-Za-z0-9_./-]+)`")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "data/", "outputs/")


def references(text: str) -> list[tuple[int, str]]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for ref in dict.fromkeys(m.group(1) for m in list(LINK.finditer(line)) + list(TICK.finditer(line))):
            if not ref.startswith(SKIP_PREFIXES):
                found.append((n, ref))      # each reference once per line, even if it is both a link and `code`
    return found


def missing(readme: Path, root: Path = ROOT) -> list[tuple[int, str]]:
    return [(n, ref) for n, ref in references(readme.read_text(encoding="utf-8"))
            if not (root / ref.rstrip("/")).exists()]


def main(argv: list[str]) -> int:
    readme = Path(argv[1]) if len(argv) > 1 else ROOT / "README.md"
    if not readme.exists():
        print(f"{readme} not found. In Docker, mount the whole repository: see the docstring of this script.")
        return 2
    bad = missing(readme, readme.resolve().parent)          # paths are relative to the README's own folder
    for n, ref in bad:
        print(f"{readme.name}:{n}: missing {ref}")
    print(f"{len(references(readme.read_text(encoding='utf-8')))} references checked, {len(bad)} missing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
