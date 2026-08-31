"""Nothing the tool needs at run time may be left out of an installed copy.

package-data used to name one family explicitly, so adding a second left
its runtime and board package out of every non-editable install. An
editable install reads the source tree, which is why that stayed invisible
from a working checkout and has to be checked here instead.
"""
import pathlib
import sys
import tomllib

# Anchored to the repository, not to the working directory: a check that
# passes or fails depending on where it was started is worse than no check.
ROOT = pathlib.Path(__file__).resolve().parent.parent

config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
patterns = config["tool"]["setuptools"]["package-data"]["niusburner"]
root = ROOT / "niusburner"

packaged = {p for pattern in patterns for p in root.glob(pattern) if p.is_file()}
on_disk = {p for p in root.rglob("*")
           if p.is_file()
           and p.suffix not in (".py", ".pyc")
           and "__pycache__" not in p.parts}

missing = sorted(str(p.relative_to(ROOT)) for p in on_disk - packaged)
if missing:
    print("these files would be left out of an installed copy:", file=sys.stderr)
    for name in missing:
        print(f"    {name}", file=sys.stderr)
    print(file=sys.stderr)
    sys.exit("widen package-data in pyproject.toml")

print(f"{len(on_disk)} data files, all packaged")
