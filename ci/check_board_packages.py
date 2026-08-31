"""The board packages are generated, so they must match the catalog."""
import pathlib
import sys

# Runnable straight from a checkout as well as from an installed copy:
# running a script puts its own directory on sys.path, not the repository
# root, so a check nobody can run locally would be a check nobody runs.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from niusburner import ide

import re

import niusburner

# Boards Manager keys an installed platform by this version, so a platform
# left behind at an older number installs as a different, older release.
# They had already drifted once: mcs51 said 0.5.0 while both PIC platforms
# still said 0.1.0.
wrong = []
for family in ide.ARCHITECTURES:
    path = ROOT / "niusburner" / "arduino" / family / "platform.txt"
    found = re.search(r"^version=(.+)$", path.read_text(encoding="utf-8"), re.M)
    if found is None:
        wrong.append(f"{family}: platform.txt has no version")
    elif found.group(1).strip() != niusburner.__version__:
        wrong.append(f"{family}: platform.txt says {found.group(1).strip()}, "
                     f"package says {niusburner.__version__}")
if wrong:
    for line in wrong:
        print(line, file=sys.stderr)
    sys.exit("platform versions must match the package version")

stale = []
for family in ide.ARCHITECTURES:
    path = ROOT / "niusburner" / "arduino" / family / "boards.txt"
    if not path.is_file():
        stale.append(f"{family}: boards.txt is missing")
    elif path.read_text(encoding="utf-8") != ide.render_boards_txt(family):
        stale.append(f"{family}: boards.txt is out of date")

if stale:
    for line in stale:
        print(line, file=sys.stderr)
    sys.exit("re-run `python -m niusburner setup`")

print(f"{len(ide.ARCHITECTURES)} board packages match the catalog "
      f"at version {niusburner.__version__}")
