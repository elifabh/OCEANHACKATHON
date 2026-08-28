#!/usr/bin/env python3
"""
dependency_audit.py -- assert that every third-party import in src/ appears
in DEPENDENCIES.md.

WHY
---
`DEPENDENCIES.md` is mandatory for the hackathon (CLAUDE.md section 3). It
has now missed FOUR packages in two days -- `scikit-learn` on 27 August,
then `xarray`, `copernicusmarine` and `pillow` on 28 August, two of which
had been in use since 10 August and sat behind the LOCKED 7.9 % / 15.2 %
Sherkin figures.

Both misses had the same cause: `ROOTS` in `src/make_dependencies.py` is
hand-maintained, so a new import is invisible to the generator until someone
remembers to add it. The 28 August note drew the right conclusion --
"a mandatory document is audited by a check, not by memory" -- and wrote the
procedure into DEPENDENCIES.md section 1. It did not write the check.

This is the check.

WHAT IT DOES
------------
Walks every `import X` / `from X import ...` in `src/*.py`, drops the
standard library and this project's own modules, and asserts the remainder
appears in DEPENDENCIES.md. Exits non-zero if anything is missing, so it can
gate a submission.

It deliberately does NOT consult the installed environment. A package that
is imported but not installed is still a declared dependency, and a package
that is installed but not imported is not one.

Run:  PYTHONPATH=src python src/dependency_audit.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
DEPS = REPO / "DEPENDENCIES.md"

# import name -> distribution name, where they differ
IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "ee": "earthengine-api",
    "osgeo": "GDAL",
    "shapely": "shapely",
    "skimage": "scikit-image",
    "netCDF4": "netcdf4",
    "bs4": "beautifulsoup4",
}


def own_modules() -> set:
    # "src" itself counts as ours: a few scripts use `from src.common import ...`
    # rather than a bare `from common import ...`, and that is our package,
    # not a distribution.
    return {p.stem for p in SRC.glob("*.py")} | {"src"}


def third_party_imports() -> dict:
    """{distribution_name: sorted list of files importing it}"""
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    mine = own_modules()
    found: dict = {}
    for f in sorted(SRC.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            print("   !! could not parse %s -- treated as no imports" % f.name,
                  file=sys.stderr)
            continue
        names: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:           # relative import -> ours
                    continue
                if node.module:
                    names.add(node.module.split(".")[0])
        for n in names:
            if n in stdlib or n in mine or n.startswith("_"):
                continue
            dist = IMPORT_TO_DIST.get(n, n)
            found.setdefault(dist, []).append(f.name)
    return {k: sorted(v) for k, v in sorted(found.items())}


def declared() -> set:
    if not DEPS.exists():
        return set()
    text = DEPS.read_text(encoding="utf-8", errors="replace").lower()
    # names appear in backticks and in table cells; match generously, then
    # rely on the exact-name test below
    return set(re.findall(r"[a-z0-9][a-z0-9._-]{1,40}", text))


def main() -> int:
    print("=" * 78)
    print("DEPENDENCY AUDIT -- every third-party import in src/ vs "
          "DEPENDENCIES.md")
    print("=" * 78)
    if not DEPS.exists():
        print("DEPENDENCIES.md not found at %s" % DEPS)
        return 2

    imports = third_party_imports()
    have = declared()
    missing: dict = {}
    for dist, files in imports.items():
        key = dist.lower()
        alt = key.replace("-", "_")
        alt2 = key.replace("_", "-")
        if key in have or alt in have or alt2 in have:
            continue
        missing[dist] = files

    print("third-party packages imported by src/: %d" % len(imports))
    for dist, files in imports.items():
        mark = "MISSING" if dist in missing else "ok"
        shown = ", ".join(files[:4]) + ("  (+%d more)" % (len(files) - 4)
                                        if len(files) > 4 else "")
        print("   %-7s %-22s %s" % (mark, dist, shown))

    print("")
    if missing:
        print("=" * 78)
        print("FAIL -- %d package(s) imported by src/ and NOT declared in "
              "DEPENDENCIES.md" % len(missing))
        print("=" * 78)
        for dist, files in missing.items():
            print("   %-22s imported by: %s" % (dist, ", ".join(files)))
        print("\nAdd them to DEPENDENCIES.md and to ROOTS in "
              "src/make_dependencies.py.")
        return 1
    print("PASS -- every third-party import in src/ is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
