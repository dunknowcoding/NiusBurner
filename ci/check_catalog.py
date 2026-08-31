"""Every board in the catalog has the fields the tool depends on."""
import pathlib
import sys

# Runnable straight from a checkout as well as from an installed copy:
# running a script puts its own directory on sys.path, not the repository
# root, so a check nobody can run locally would be a check nobody runs.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from niusburner import boards

catalog = boards.all_boards()
if not catalog:
    sys.exit("the catalog is empty")

problems = []
for name, board in sorted(catalog.items()):
    if board.code_size <= 0:
        problems.append(f"{name}: no flash size")
    if board.iram_size <= 0:
        problems.append(f"{name}: no RAM size")
    if not board.programmer:
        problems.append(f"{name}: names no programmer")
    if not board.note:
        problems.append(f"{name}: has no description")

if problems:
    for line in problems:
        print(line, file=sys.stderr)
    sys.exit(f"{len(problems)} catalog problem(s)")

print(f"{len(catalog)} boards, all well formed")
