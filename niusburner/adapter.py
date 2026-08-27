"""Mount library folders so C++ facades lower to C without editing NiusBurner.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

A library is mounted when its tree contains ``niusburner/adapter.json``.
NiusBurner does not import the library. It reads that JSON and optional
bind ``.c`` / ``.h`` next to it. NiusDisplay is the only adapter shipped
today; dropping ``NiusIMU/niusburner/adapter.json`` is enough to add
another (no change to ``cxxlower.py``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
REPO = HERE.parent
BUNDLED = HERE / "adapters"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AdapterError(ValueError):
    def __init__(self, hit: str, detail: str = "") -> None:
        self.hit = hit
        self.detail = detail
        super().__init__(detail or hit)


@dataclass
class BoundObject:
    cls: str
    name: str
    fields: dict[str, str]
    spec: dict[str, Any]
    adapter_name: str


@dataclass
class RewriteInfo:
    adapters: tuple[str, ...]
    classes: tuple[str, ...]
    headers: tuple[str, ...]
    stems: tuple[str, ...]
    defines: tuple[str, ...]
    needs_xram: bool
    bind_sources: tuple[Path, ...]


@dataclass(frozen=True)
class LibraryAdapter:
    name: str
    root: Path
    data: dict[str, Any]
    bundled: bool = False

    @property
    def class_names(self) -> tuple[str, ...]:
        classes = self.data.get("classes") or {}
        return tuple(classes.keys())

    @property
    def global_names(self) -> tuple[str, ...]:
        """Objects that exist without a constructor, the way Wire and SPI do."""
        globals_ = self.data.get("globals") or {}
        return tuple(globals_.keys())

    def applies(self, text: str) -> bool:
        from .cxxlower import _code_words

        body = _code_words(text)
        for inc in self.data.get("match_includes") or []:
            if re.search(rf"\b{re.escape(Path(inc).name)}\b", text, re.I):
                return True
        for name in self.class_names:
            if re.search(rf"\b{re.escape(name)}\b", body):
                return True
        for item in self.data.get("refuse") or []:
            token = item.get("token") or ""
            if token and re.search(rf"\b{re.escape(token)}\b", body):
                return True
        return False


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def mount_roots(explicit: list[Path] | None = None) -> list[Path]:
    """Library trees that may contain niusburner/adapter.json."""
    roots: list[Path] = []
    for path in explicit or []:
        roots.append(Path(path))
    env = os.environ.get("NIUSBURNER_LIBS") or ""
    for part in env.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part))
    parent = REPO.parent
    if parent.is_dir():
        try:
            for child in parent.iterdir():
                if (child / "niusburner" / "adapter.json").is_file():
                    roots.append(child)
        except OSError:
            pass
    from . import display as display_mod

    for book in display_mod.arduino_sketchbooks():
        libdir = book / "libraries"
        if not libdir.is_dir():
            continue
        try:
            for child in libdir.iterdir():
                if (child / "niusburner" / "adapter.json").is_file():
                    roots.append(child)
        except OSError:
            continue
    return _unique_paths(roots)


def _load_json(path: Path, *, bundled: bool) -> LibraryAdapter | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    root = path.parent.parent if path.parent.name.lower() == "niusburner" else path.parent
    return LibraryAdapter(str(data["name"]), root, data, bundled=bundled)


def bundled_adapters() -> list[LibraryAdapter]:
    found: list[LibraryAdapter] = []
    if not BUNDLED.is_dir():
        return found
    for child in sorted(BUNDLED.iterdir()):
        path = child / "adapter.json"
        if path.is_file():
            loaded = _load_json(path, bundled=True)
            if loaded is not None:
                found.append(loaded)
    return found


def load_adapters(explicit: list[Path] | None = None) -> list[LibraryAdapter]:
    """Mounted adapters first (by name), then bundled fallbacks."""
    by_name: dict[str, LibraryAdapter] = {}
    for root in mount_roots(explicit):
        path = root / "niusburner" / "adapter.json"
        if not path.is_file():
            # `--library` / `--mount` may point at the adapter folder itself.
            alt = root / "adapter.json"
            path = alt if alt.is_file() else path
        if not path.is_file():
            continue
        loaded = _load_json(path, bundled=False)
        if loaded is not None and loaded.name not in by_name:
            by_name[loaded.name] = loaded
    for bundled in bundled_adapters():
        if bundled.name not in by_name:
            by_name[bundled.name] = bundled
    return list(by_name.values())


def _bind_file(adapter: LibraryAdapter, name: str) -> Path | None:
    """Locate a bind .c listed by adapter.json for one lowered class."""
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    if adapter.bundled:
        candidates = [adapter.root / rel]
    else:
        # A mounted library may not carry the C support itself, so the
        # bundled copy is the fallback. Match the folder by name without
        # assuming a case, because `adapters/NiusDisplay` resolves on Windows
        # whatever case is asked for and on Linux only the exact one.
        candidates = [adapter.root / "niusburner" / rel, adapter.root / rel]
        wanted = adapter.name.lower()
        if BUNDLED.is_dir():
            for child in BUNDLED.iterdir():
                if child.is_dir() and child.name.lower() == wanted:
                    candidates.append(child / rel)
    for path in candidates:
        if path.is_file():
            return path
    return None


_SIDE_EFFECT = re.compile(r"\+\+|--|\(|=[^=]|(?<![=!<>])=$")


def _is_reusable(expr: str) -> bool:
    """True when substituting *expr* twice cannot change what the code does.

    Anything with a call, an assignment or an increment is evaluated for its
    effects as well as its value, so pasting it into a template twice would
    run it twice. That is a silent behaviour change, which is exactly what
    this translator must not do.
    """
    return not _SIDE_EFFECT.search(expr.strip())


def _render(template: str, name: str, args: list[str], fields: dict[str, str]) -> str:
    mapping = {"name": name, **fields}
    for index, arg in enumerate(args):
        mapping[str(index)] = arg

    used: dict[str, int] = {}

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in mapping:
            raise AdapterError(
                name,
                f"adapter template {template!r} needs {{{key}}} but it is not set",
            )
        used[key] = used.get(key, 0) + 1
        value = mapping[key]
        if used[key] > 1 and not _is_reusable(value):
            raise AdapterError(
                name,
                f"{value!r} would be evaluated {used[key]} times: this call "
                "expands to a form that uses the argument more than once. "
                "Assign it to a variable first.",
            )
        return value

    return re.sub(r"\{([A-Za-z0-9_]+)\}", repl, template)


def _method_args(method: str, spec: dict[str, Any], args: list[str]) -> list[str]:
    if spec.get("refuse"):
        raise AdapterError(method, str(spec["refuse"]))
    help_text = spec.get("help")
    args = list(args)
    if "args" in spec:
        want = int(spec["args"])
        if len(args) != want:
            raise AdapterError(
                method,
                help_text or f"{method}() takes {want} argument(s)")
        return args
    min_args = int(spec.get("min_args", 0))
    max_args = int(spec.get("max_args", min_args))
    if not (min_args <= len(args) <= max_args):
        raise AdapterError(
            method,
            help_text or f"{method}() takes {min_args}..{max_args} arguments")
    if "pad" in spec:
        while len(args) < max_args:
            args.append(str(spec["pad"]))
        return args
    trailing = [str(x) for x in (spec.get("trailing") or [])]
    # Optional arguments are the last ``len(trailing)`` slots; missing ones
    # take trailing defaults in order.
    missing = max_args - len(args)
    if missing:
        if len(trailing) < missing:
            raise AdapterError(method, f"{method}() is missing defaults")
        args.extend(trailing[-missing:] if len(trailing) == max_args - min_args else trailing[:missing])
    return args


def _lower_ctors(
    text: str,
    adapter: LibraryAdapter,
    host: Any,
) -> tuple[str, list[BoundObject]]:
    objects: list[BoundObject] = []
    spans: list[tuple[int, int, str]] = []
    classes: dict[str, Any] = adapter.data.get("classes") or {}
    n = len(text)
    i = 0
    while i < n:
        jumped = host._skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        hit_cls = None
        for cls in classes:
            if host._at_word(text, i, cls):
                hit_cls = cls
                break
        if hit_cls is None:
            i += 1
            continue
        spec = classes[hit_cls]
        ctor = spec.get("ctor") or {}
        min_args = int(ctor.get("min_args", 0))
        max_args = int(ctor.get("max_args", min_args))
        j = i + len(hit_cls)
        while j < n and text[j].isspace():
            j += 1
        match = _IDENT.match(text, j)
        if not match:
            i += 1
            continue
        name = match.group(0)
        j = match.end()
        while j < n and text[j].isspace():
            j += 1
        if j < n and text[j] == "(":
            close = host._matching_close(text, j)
            args = host._split_args(text[j + 1:close])
            k = close + 1
        elif min_args == 0:
            args = []
            k = j
        else:
            raise AdapterError(hit_cls, f"{name!r} is not a constructor call")
        if not (min_args <= len(args) <= max_args):
            raise AdapterError(
                hit_cls,
                ctor.get("help") or f"constructor takes {min_args}..{max_args} arguments",
            )
        field_names = list(ctor.get("fields") or [])
        defaults = ctor.get("defaults") or {}
        fields: dict[str, str] = {}
        for index, field_name in enumerate(field_names):
            if index < len(args):
                fields[field_name] = args[index]
            elif field_name in defaults:
                fields[field_name] = str(defaults[field_name])
        while k < n and text[k].isspace() and text[k] != "\n":
            k += 1
        if k < n and text[k] == ";":
            k += 1
        decl = spec.get("c_decl") or "static void *{name};"
        spans.append((i, k, _render(decl, name, args, fields)))
        objects.append(BoundObject(hit_cls, name, fields, spec, adapter.name))
        i = k
    return host._apply(text, spans), objects


def _lower_methods(text: str, objects: list[BoundObject], host: Any) -> str:
    by_name = {obj.name: obj for obj in objects}
    if not by_name:
        return text
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = host._skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        match = _IDENT.match(text, i)
        if not match or match.group(0) not in by_name:
            i += 1
            continue
        name = match.group(0)
        j = match.end()
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != ".":
            i = match.end()
            continue
        j += 1
        while j < n and text[j].isspace():
            j += 1
        method_match = _IDENT.match(text, j)
        if not method_match:
            raise AdapterError(name, f"{name}. is not a method call")
        method = method_match.group(0)
        j = method_match.end()
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != "(":
            raise AdapterError(method, f"{name}.{method} is not a call")
        close = host._matching_close(text, j)
        args = host._split_args(text[j + 1:close])
        obj = by_name[name]
        methods: dict[str, Any] = obj.spec.get("methods") or {}
        if method not in methods:
            known = ", ".join(sorted(k for k in methods if k != "ready"))
            raise AdapterError(
                method,
                f"{obj.cls}.{method}() is not in the BASIC subset ({known})",
            )
        spec = methods[method]
        filled = _method_args(method, spec, args)
        emit = spec.get("emit")
        if filled and spec.get("emit_char") and filled[0].strip().startswith("'"):
            emit = spec["emit_char"]
        if not emit:
            raise AdapterError(method, spec.get("refuse") or f"{method} cannot be lowered")
        spans.append((i, close + 1, _render(emit, name, filled, obj.fields)))
        i = close + 1
    return host._apply(text, spans)


def _drop_includes(text: str, names: list[str]) -> str:
    for name in names:
        pattern = re.compile(
            rf'^[ \t]*#[ \t]*include[ \t]*[<"]{re.escape(name)}[>"][ \t]*\r?$',
            re.M | re.I,
        )
        text = pattern.sub("", text)
    return text


def _check_requires(obj: BoundObject, board: Any) -> None:
    """Refuse a facade the board has no way to drive.

    A bit-banged bus counts as provided: the capability table exists to
    separate "this part cannot do it at all" from "this part does it in
    software", not to insist on a hardware peripheral.
    """
    if board is None:
        return
    for feature in obj.spec.get("requires") or []:
        if board.provides(str(feature)):
            continue
        raise AdapterError(
            obj.cls,
            f"{obj.cls} needs {feature}, and {board.id} has none. "
            "`python -m niusburner boards --features` lists what each board "
            "provides; a feature shown as 'software' is bit-banged and works.",
        )


def _globals_in(text: str, adapter: LibraryAdapter, host: Any) -> list[BoundObject]:
    """Pre-declared objects such as Wire and SPI that appear in *text*."""
    body = host._code_words(text)
    found: list[BoundObject] = []
    for name, spec in (adapter.data.get("globals") or {}).items():
        if re.search(rf"\b{re.escape(name)}\b", body):
            found.append(BoundObject(name, name, {}, spec, adapter.name))
    return found


def rewrite(
    text: str,
    adapters: list[LibraryAdapter],
    host: Any,
    board: Any = None,
) -> tuple[str, RewriteInfo]:
    """Lower mounted library facades in *text*. *host* is the cxxlower module."""
    from .cxxlower import _code_words

    body = _code_words(text)
    used: list[LibraryAdapter] = [a for a in adapters if a.applies(text)]
    for adapter in used:
        for item in adapter.data.get("refuse") or []:
            token = item.get("token") or ""
            if token and re.search(rf"\b{re.escape(token)}\b", body):
                raise AdapterError(token, item.get("detail") or token)

    objects: list[BoundObject] = []
    out = text
    for adapter in used:
        out, more = _lower_ctors(out, adapter, host)
        objects.extend(more)
        objects.extend(_globals_in(out, adapter, host))
    for obj in objects:
        _check_requires(obj, board)
    out = _lower_methods(out, objects, host)

    headers: list[str] = []
    stems: list[str] = []
    defines: list[str] = []
    bind: list[Path] = []
    needs_xram = False
    classes_used: list[str] = []
    drop: list[str] = []
    had_include = False

    for adapter in used:
        drop.extend(adapter.data.get("drop_includes") or [])
        for inc in adapter.data.get("match_includes") or []:
            if re.search(rf"\b{re.escape(Path(inc).name)}\b", text, re.I):
                had_include = True
                for header in adapter.data.get("bare_include_headers") or []:
                    if header not in headers:
                        headers.append(header)

    for obj in objects:
        classes_used.append(obj.cls)
        for header in obj.spec.get("headers") or []:
            if header not in headers:
                headers.append(header)
        for stem in obj.spec.get("stems") or []:
            if stem not in stems:
                stems.append(stem)
        for define in obj.spec.get("defines") or []:
            if define not in defines:
                defines.append(define)
        if obj.spec.get("needs_xram"):
            needs_xram = True

    if objects or had_include:
        out = _drop_includes(out, drop)
        for header in headers:
            line = f'#include "{header}"'
            if line not in out:
                out = host._inject_include(out, line)

    code = host._code_words(out)
    for adapter in used:
        for name in (*adapter.class_names, *adapter.global_names):
            if re.search(rf"\b{re.escape(name)}\b", code):
                raise AdapterError(
                    name,
                    f"could not rewrite every {name} use. Only "
                    f"{name}.method(...) calls are lowered -- taking its "
                    "address, aliasing it, or passing it on is not.",
                )

    by_adapter = {item.name: item for item in used}
    for obj in objects:
        adapter = by_adapter.get(obj.adapter_name)
        if adapter is None:
            continue
        for name in obj.spec.get("bind") or []:
            path = _bind_file(adapter, str(name))
            if path is not None and path not in bind:
                bind.append(path)

    return out, RewriteInfo(
        adapters=tuple(a.name for a in used),
        classes=tuple(dict.fromkeys(classes_used)),
        headers=tuple(headers),
        stems=tuple(stems),
        defines=tuple(defines),
        needs_xram=needs_xram,
        bind_sources=tuple(bind),
    )

