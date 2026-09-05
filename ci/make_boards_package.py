"""Build the Boards Manager archives and the package index.

NiusBurner is a boards platform, not a library, so it is distributed the way
platforms are: one archive per architecture plus a JSON index, and the user
pastes the index URL into File > Preferences > Additional Boards Manager
URLs. The Library Manager is the wrong shelf -- it is for C++ libraries a
sketch includes, and it would reject this on sight.

Each archive is self-contained apart from Python itself. It carries the
platform and a copy of the niusburner package under tools/, which is what
nb_host falls back to when nothing has run `setup`: a Boards Manager install
records no interpreter and no checkout, so without the bundled copy the
platform would install and then fail on the first Verify.

The package's own arduino/ directory is left out of that copy. It holds
these same platforms, so including it would put every architecture inside
every archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from niusburner import boards as boards_mod          # noqa: E402
from niusburner import ide                           # noqa: E402

PACKAGE = ide.VENDOR
MAINTAINER = "NiusRobotLab"
WEBSITE = "https://github.com/dunknowcoding/NiusBurner"
EMAIL = "felixneverflyaway@gmail.com"
DEFAULT_BASE = WEBSITE + "/releases/download"


def version() -> str:
    text = (ROOT / "niusburner" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'__version__ = "([^"]+)"', text)
    if not found:
        raise SystemExit("no __version__ in niusburner/__init__.py")
    return found.group(1)


def platform_name(architecture: str) -> str:
    text = (ROOT / "niusburner" / "arduino" / architecture
            / "platform.txt").read_text(encoding="utf-8")
    found = re.search(r"^name=(.+)$", text, re.M)
    return found.group(1).strip() if found else architecture


def stage(architecture: str, into: pathlib.Path) -> pathlib.Path:
    """Lay out one platform exactly as it must appear once installed."""
    root = into / f"{PACKAGE}-{architecture}-{version()}"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(ROOT / "niusburner" / "arduino" / architecture, root)

    bundled = root / "tools" / "niusburner"

    def skip(directory: str, names: list[str]) -> set[str]:
        """Drop caches, and the platform tree -- but only at the package root.

        A pattern of "arduino" cannot be used here: shutil matches with
        fnmatch, which is case-insensitive on Windows, so it also swallows
        adapters/Arduino and the archive installs with no runtime at all.
        """
        drop = {n for n in names if n == "__pycache__" or n.endswith(".pyc")}
        if pathlib.Path(directory).resolve() == (ROOT / "niusburner").resolve():
            drop.add("arduino")
        return drop

    shutil.copytree(ROOT / "niusburner", bundled, ignore=skip)

    for junk in list(root.rglob("__pycache__")) + list(root.rglob("*.path")):
        shutil.rmtree(junk, ignore_errors=True) if junk.is_dir() else junk.unlink()
    return root


def archive(root: pathlib.Path, into: pathlib.Path) -> pathlib.Path:
    """One .tar.bz2 with a single top-level directory, built deterministically."""
    out = into / (root.name + ".tar.bz2")
    members = sorted(p for p in root.rglob("*"))
    with tarfile.open(out, "w:bz2") as tar:
        for path in members:
            info = tar.gettarinfo(str(path), arcname=str(
                pathlib.PurePosixPath(root.name)
                / path.relative_to(root).as_posix()))
            # Reproducible: the same input must give the same checksum.
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if info.isfile():
                with open(path, "rb") as fh:
                    tar.addfile(info, fh)
            else:
                tar.addfile(info)
    return out


def platform_version(architecture: str) -> str:
    """The version a platform declares to Boards Manager once installed."""
    text = (ROOT / "niusburner" / "arduino" / architecture
            / "platform.txt").read_text(encoding="utf-8")
    found = re.search(r"^version=(.+)$", text, re.M)
    return found.group(1).strip() if found else ""


def check_versions(ver: str) -> None:
    """Refuse to build archives that disagree with themselves.

    The version is written in five places: the package, and one platform.txt
    per architecture. The index copies the package's, so bumping only that
    produces archives whose index says one version and whose platform.txt
    says another -- and Boards Manager keys an installed platform by the
    platform.txt one, so the IDE would report the old version for new code.

    ci/check_board_packages.py already catches the mismatch, but only after a
    release has been cut from it, which is exactly too late. Checking here
    means the archives cannot be built wrong in the first place.
    """
    wrong = [f"{a}: platform.txt says {platform_version(a) or 'nothing'}"
             for a in ide.ARCHITECTURES if platform_version(a) != ver]
    if wrong:
        raise SystemExit(
            "\n".join([f"refusing to build: the package is {ver} but",
                       *(f"  {line}" for line in wrong),
                       "bump version= in each platform.txt to match."]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", type=pathlib.Path,
                    default=ROOT / "dist" / "boards-manager")
    ap.add_argument("--base-url", default=DEFAULT_BASE,
                    help="where the archives will be hosted; the tag is added")
    args = ap.parse_args()

    ver = version()
    check_versions(ver)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    staging = out / "staging"
    staging.mkdir(exist_ok=True)

    catalog = boards_mod.all_boards()
    platforms = []
    for architecture in ide.ARCHITECTURES:
        root = stage(architecture, staging)
        tarball = archive(root, out)
        raw = tarball.read_bytes()
        listed = sorted(b.part.upper() for b in catalog.values()
                        if b.family == architecture)
        platforms.append({
            "name": platform_name(architecture),
            "architecture": architecture,
            "version": ver,
            "category": "Contributed",
            "help": {"online": WEBSITE},
            "url": f"{args.base_url}/v{ver}/{tarball.name}",
            "archiveFileName": tarball.name,
            "checksum": "SHA-256:" + hashlib.sha256(raw).hexdigest(),
            "size": str(len(raw)),
            "boards": [{"name": name} for name in listed],
            "toolsDependencies": [],
        })
        print(f"  {architecture:6} {len(listed):3} boards  "
              f"{len(raw) / 1024:7.1f} KB  {tarball.name}")

    index = {"packages": [{
        "name": PACKAGE,
        "maintainer": MAINTAINER,
        "websiteURL": WEBSITE,
        "email": EMAIL,
        "help": {"online": WEBSITE},
        "platforms": platforms,
        # The compilers are not redistributed here; each comes from its own
        # vendor under its own licence, which is also why this list is empty
        # rather than pinning a toolchain the user must accept terms for.
        "tools": [],
    }]}

    index_path = out / f"package_{PACKAGE}_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(staging, ignore_errors=True)
    print(f"\n  index: {index_path}")
    print(f"  add this URL in the IDE once it is hosted:")
    print(f"    {args.base_url}/v{ver}/{index_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
