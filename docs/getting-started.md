# Getting started

Everything you need to buy, install and wire before the first upload. Follow
it once per machine.

If you already have the tools, skip to [workflow.md](workflow.md).

---

## 1. What to buy

None of it is expensive, and none of it is special. These are the commodity
parts the tool is built around.

### For the 8051 parts

| Item | Roughly | What to look for |
|---|---|---|
| **USB-ISP programmer** | $3–5 | Sold as "USB ISP 下载线" or "USB-ISP programmer for 51/AVR". The one this tool drives enumerates as **VID `03EB` / PID `C8B4`** and speaks HID. A blue plastic case with a 10-pin IDC ribbon is the usual shape. |
| **10-pin IDC ribbon cable** | $1 | Normally in the box with the programmer. |
| **AT89S52 (or any part in the table)** | $1–2 | DIP-40 for breadboarding. Ask for AT89**S**52, not AT89**C**52 — the C part has no ISP interface and cannot be programmed through the header (see [families/8051.md](families/8051.md)). |
| **11.0592 MHz crystal + 2 × 22 pF** | under $1 | Not optional. The 8051 has no internal oscillator, and 11.0592 MHz is the frequency that makes the standard baud rates exact. |
| **USB-TTL serial adapter** | $2 | CH340 or CH341. Only needed for `Serial` output, and for the STC parts, where it *is* the programmer. |

A ready-made "51 development board" bundles the socket, crystal, reset
circuit, power and the ISP header for about $6, and saves a lot of wiring.

### For the PIC parts

| Item | Roughly | What to look for |
|---|---|---|
| **PICkit 3** | $10–20 | Clones work. It enumerates as **VID `04D8` / PID `900A`**. |
| **PIC16F877A (or any part in the table)** | $2–4 | DIP-40. |
| **20 MHz crystal + 2 × 22 pF** | under $1 | The 16F87x family has no internal oscillator either. The 18-pin parts (16F628A, 16F88) *do*, and can run without one. |
| **5-pin ICSP header** | — | MCLR, VDD, VSS, PGD, PGC. Most PIC boards bring it out already. |

---

## 2. Install the compiler

### SDCC — for the 8051 parts

Free and open source. NiusBurner finds it on `PATH`, at
`C:\Program Files\SDCC\bin\sdcc.exe`, or via `SDCC_HOME`.

| | |
|---|---|
| **Windows** | Download the installer from <https://sourceforge.net/projects/sdcc/files/> and run it. Leave "add to PATH" ticked. |
| **Linux** | `sudo apt install sdcc` — or the tarball from the same page if your distribution ships an old one. |
| **macOS** | `brew install sdcc` |

Check it:

```bash
sdcc --version
python -m niusburner detect
```

### XC8 — for the PIC parts

Free tier, from <https://www.microchip.com/mplab/compilers>. Registration is
required; there is no way around that, and nothing here tries to script it.
The free tier is unoptimised but complete — every part in the table compiles
under it.

Install to the default location. NiusBurner finds it, or you can record the
path yourself:

```bash
python -m niusburner setup --xc8 "C:\Program Files\Microchip\xc8\v3.00\bin\xc8-cc.exe"
```

---

## 3. Install the programmer software and drivers

### USB-ISP (8051)

**No driver to install.** It is a HID device, so Windows binds `HidUsb`
automatically the first time you plug it in.

> **Do not run Zadig against it.** Replacing `HidUsb` with WinUSB stops it
> working with this tool. If that has already happened, open Zadig, select the
> device, choose **HidUsb**, and click *Replace Driver*.

Check it:

```bash
python -m niusburner probe at89s52 --confirm at89s52
```

A working programmer with a powered part on the header answers with the
signature.

### PICkit 3

The PICkit 3 is driven through **ipecmd**, which ships inside MPLAB X.

> ### ⚠️ You need MPLAB X **5.x**, not 6.x or newer
>
> Microchip removed PICkit 3 support after the 5.x line. A modern MPLAB X
> will find the programmer, then fail with a misleading *"Could not find
> device"*. NiusBurner detects the version and tells you this rather than
> letting you chase the wiring.
>
> **MPLAB X v5.35** is the last release with PICkit 3 support:
> <https://www.microchip.com/en-us/development-tools-tools-and-software/mplab-x-ide>
> (see *Downloads Archive*). It installs alongside a newer MPLAB X without
> conflict.

Windows binds the driver automatically. Record the path if it is not found:

```bash
python -m niusburner setup --pickit3 "H:\MPLABX\v5.35\mplab_platform\mplab_ipe\ipecmd.exe"
python -m niusburner probe 16F877A --confirm 16F877A
```

### USB-TTL serial adapter (CH340/CH341)

Recent Windows installs the driver over Windows Update. If the port never
appears, get the vendor driver from
<https://www.wch-ic.com/downloads/CH341SER_EXE.html>. On Linux and macOS the
`ch341` driver is in-tree; no install needed.

---

## 4. Wire it up

### 8051 — ISP header

Ten pins, and **pin 1 alignment is the mistake everyone makes**. Full detail,
including the target-side pinout, is in
[wiring/usbasp-idc10.md](wiring/usbasp-idc10.md).

```
MOSI  1 ●  2  VCC
NC    3    4  GND
RST   5    6  GND
SCK   7    8  GND
MISO  9   10  GND
```

**EA/VPP (DIP-40 pin 31) must be tied to VCC.** It is not on the header and
nothing will warn you. With EA low the part fetches every instruction from
external memory: ISP still enables, the signature still reads, the image
still verifies — and none of it ever runs.

### PIC — ICSP header

Five signals, pin 1 marked with an arrow on the programmer:

```
1 MCLR/VPP    2 VDD    3 VSS(GND)    4 PGD(data)    5 PGC(clock)
```

Both families: the target needs its own power. The 8051 programmer's VCC pin
can supply a small board; the PICkit 3 refuses to supply a board that already
has power, which is the safe behaviour.

---

## 5. Set up the Arduino IDE

```bash
python -m niusburner setup --sketchbook ~/Documents/Arduino
```

That writes a board package into the sketchbook. Restart the IDE, then:

1. **Tools → Board → NiusBurner 8051 (SDCC)** (or **NiusBurner PIC (XC8)**),
   and pick your part.
2. **Tools → Programmer** — USB-ISP HID for the 8051 parts, PICkit 3 for the
   PIC parts.
3. **Tools → Port** — only needed for the STC parts, which are programmed
   through the serial adapter.

**Verify** compiles. **Upload** erases and programs. There is no third step.

Full menu reference: [arduino-ide.md](arduino-ide.md).

---

## 6. First upload

```bash
python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
```

or press **Upload** in the IDE. Either way you should see the erase, the
program, the verify and the release from reset.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `no ISP acknowledge` | Pin 1 reversed, no crystal, or the part is an AT89**C** rather than an AT89**S**. |
| Signature reads `FF FF FF` or `00 00 00` | The target has no power, or MISO is not connected. |
| Verify passes, the part does nothing | **EA (pin 31) is not tied to VCC**, or there is no crystal. |
| `Could not find device` from the PIC tools | MPLAB X 6.x or newer. See the warning in §3. |
| The PIC programmer refuses to power the target | The board already has its own supply. Select the plain PICkit 3 entry, not the one that powers the target. |
| `sdcc not found` | Not on `PATH`. Re-run the installer with the PATH option, or `setup --sdcc <path>`. |
| The Upload button says the part cannot be flashed | That part has no in-circuit programming interface at all; it needs a parallel programming socket. |

`python -m niusburner detect` prints what was found and what was not, which
is usually faster than guessing.
