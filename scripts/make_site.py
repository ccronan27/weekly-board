"""Assemble the deployable site in _site/: site/ files plus data/build/.

    python scripts/make_site.py && python -m http.server -d _site 8000
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    build = ROOT / "data" / "build"
    if not (build / "meta.json").exists() or not list(build.glob("*.json")):
        print("data/build is empty. Run the pipeline first. Not assembling an empty site.", file=sys.stderr)
        return 1
    out = ROOT / "_site"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(build, out / "data" / "build")
    print("site assembled in", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
