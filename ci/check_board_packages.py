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

print(f"{len(ide.ARCHITECTURES)} board packages match the catalog")
