"""Run the vendored stcgal as a module.

Mirrors upstream's entry point, with the import made relative so this
copy is the one that runs.
"""

import sys

from . import frontend

if __name__ == "__main__":
    sys.exit(frontend.cli())
