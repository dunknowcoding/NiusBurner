# Toolchains

Everything installs to **`C:\embd_toolchains\`**. Nothing installs into a
repository, ever.

Override the root with `EMBD_TOOLCHAINS` if you keep it elsewhere.

## Why nothing is vendored

Committing a compiler into a git repo looks convenient and is a mistake:

- **Licensing.** IAR, Microchip and TI tools are not ours to redistribute.
  SDCC is GPL. Vendoring any of them changes what this repository *is*.
- **It goes stale silently.** A pinned copy keeps working until a target needs
  a fix that landed upstream two years ago, and nothing announces that.
- **Size.** These are hundreds of megabytes each. A clone should be seconds.

So the registry describes tools; it never contains them. `test_registry.py`
enforces that by walking the tree for binaries and by capping the repo size —
an ignore rule alone would not catch a file committed before the rule existed.

## Layout

```
C:\embd_toolchains\
  pic\xc8\v3.00\           pic\xc16\v2.10\      pic\xc32\v6.00\
  msp430\msp430-gcc-9.3.1.11_win64\
  c2000\25.11.1.LTS\ti-cgt-c2000_25.11.1.LTS\
  riscv\xpack-riscv-none-elf-gcc-15.2.0-1\
  _downloads\             installer archives, safe to delete
```

Version directories are kept, so an upgrade is additive and a regression can be
bisected against the exact compiler that produced it.

## Detection

`python -m niusburner detect` probes rather than trusts. Three forms:

| Form | Used when | Proves |
|---|---|---|
| `cmd` | the tool is on PATH and has `--version` | it **runs**, and is the right tool |
| `path` | a fixed install location | the file exists |
| `glob` | vendor installs under a version directory | the file exists; newest wins |

`cmd` is preferred wherever possible: it is the only form that separates
"installed" from "present but broken", and its `match` field catches a PATH
collision — something else named `avrdude` earlier on PATH would otherwise be
accepted and fail confusingly much later.

**Globs are version-agnostic on purpose.** Every one of these was first written
as a fixed path, and every one was wrong; the first honest `detect` run reported
seven toolchains missing that were installed and building fine. A toolchain
upgrade must not turn into "missing".

## Current state

Run it — this document does not restate the result, because a table here would
be a claim about your machine that nobody checked:

```bash
conda run -n embedded python -m niusburner detect
```

## Adding one

1. Install it under `C:\embd_toolchains\<family>\<version>\`.
2. Add an entry to `niusburner/toolchains.json` with a `detect` rule and an
   `install` URL.
3. Run `detect` and confirm it is found.
4. `pytest tests/` — the invariants apply to the new entry too.

`install` is a URL and an instruction, not an automated installer. Several of
these vendors require accepting a licence or registering, and scripting around
that would be fragile and wrong.
