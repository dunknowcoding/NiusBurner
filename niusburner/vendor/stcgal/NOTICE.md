# stcgal, vendored

Upstream: <https://github.com/grigorig/stcgal>
Version: 1.10
Copyright (c) 2013-2015 Grigori Goronzy \<greg@chown.ath.cx\>
Licence: MIT — the full text is in the header of every source file here.

## Why it is carried here

The STC families are programmed through their own serial bootloader, and
stcgal is the implementation of that protocol. Carrying it means an
upload works from a clean checkout, instead of failing on a machine where
one more package was never installed. That is the whole reason: fewer
things to set up before a board can be programmed.

## What was changed

Only these. Everything else is upstream, byte for byte.

**Imports made relative.** `from stcgal.x import y` became `from .x
import y`, so this copy is used rather than a separately installed one
that may be a different version.

**Packet tracing removed.** The tracing flag, its command-line option and
the two printers behind it are gone. `dump_packet` remains as a no-op:
the protocol handlers call it from a great many places, and removing
those calls would mean touching code that is otherwise unmodified.

**The STC8G protocol selection was corrected.** Upstream chooses the
exchange by the requested trim frequency rather than by the part:

```python
if opts.trim < 27360:
    self.protocol = Stc8dProtocol(...)   # the STC8A exchange
else:
    self.protocol = Stc8gProtocol(...)
```

An STC8G or STC8H does not answer the STC8A exchange, so asking for
`stc8g` at any ordinary trim -- 22.1184 MHz, say -- sent a challenge the
part ignores, and the upload failed with a `pulse timeout` that reads
like a wiring or latency fault and is neither. The part determines the
exchange, so the selection now follows the part. Upstream marks the
original as a hack pending a full STC8G implementation.
