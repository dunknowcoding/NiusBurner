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
| **A PIC** | $1–4 | Any part in the tables in [families/pic.md](families/pic.md): PIC16F877A (DIP-40) and PIC16F628A (DIP-18) are the common ones, PIC18F4550 if you want more room, PIC12F675 for something tiny. |
| **20 MHz crystal + 2 × 22 pF** | under $1 | Needed by the 16F87x and PIC18 parts. The 18-pin (16F628A, 16F88) and 8-pin (12F6xx) parts have an internal oscillator and run without one. |
| **5-pin ICSP header** | — | MCLR, VDD, VSS, PGD, PGC. Most PIC boards bring it out already. |

---

## 2. Install Python (Windows first)

NiusBurner is a Python program. The Arduino IDE calls it to compile and to
program, so Python has to be there — but **nothing gets installed into
Python**. There is no `pip install`, no virtual environment, no packages to
manage. `setup` writes down which Python you ran it with and where this
folder is, and the IDE uses those two facts from then on.

**Python 3.10 or newer.** That is the only requirement.

### Windows

Windows is where this goes wrong, and it always goes wrong the same way.

> ### ⚠️ The `python` already on your PC probably is not Python
>
> A clean Windows ships an **App execution alias**: a zero-byte placeholder
> named `python.exe` that opens the Microsoft Store instead of running
> anything. Type `python` and a Store page appears, or the window just
> closes. It is not Python and it will never work.
>
> You can see it for what it is:
>
> ```
> where python
> ```
>
> If the answer contains `AppData\Local\Microsoft\WindowsApps`, that is the
> placeholder, not an interpreter.

**Install the real thing** from <https://www.python.org/downloads/>. Take the
64-bit Windows installer.

On the installer's first page, before pressing Install:

- ✅ **Tick "Add python.exe to PATH".** This is the single most important
  click in this document. Without it `python` keeps finding the Store
  placeholder, and every instruction here looks broken.
- "Install Now" is fine. Administrator rights are not needed — the per-user
  install works.

Then **open a new terminal** — one that was already open still has the old
PATH — and check:

```
python --version
```

You want `Python 3.10` or higher. If you still get a Store page or an error,
use the launcher the installer always registers:

```
py -3 --version
```

If `py -3` works and `python` does not, either use `py -3` in place of
`python` everywhere below, or switch the placeholder off:
**Settings → Apps → Advanced app settings → App execution aliases**, and turn
off both **python.exe** and **python3.exe**.

### If you already have several Pythons

Anaconda, Miniconda, the Microsoft Store, a python.org install, one that came
bundled with another program — a normal machine ends up with two or three.
That is fine and you do not have to remove any of them. One rule matters:

> **The Python you run `setup` with is the Python the Arduino IDE will use.**

`setup` records that interpreter's full path, so the IDE never guesses and
never depends on PATH afterwards. Check which one you are about to use:

```
python -c "import sys; print(sys.executable)"
```

If that is the one you want, carry on. If not, run `setup` with the one you
do want, by its full path:

```
"C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe" -m niusburner setup
```

Conda users: activating the environment first works the same way, and that
environment's interpreter is what gets recorded.

**If you later move, upgrade or uninstall that Python, re-run `setup`.** It
is the one thing that needs saying twice, and it takes a second. Otherwise
the IDE reports that it cannot find the tool, naming the path that went away.

### Linux and macOS

Almost always present already, and almost always new enough:

```bash
python3 --version
```

If it is older than 3.10: `sudo apt install python3` on Debian and Ubuntu,
`brew install python` on macOS. Use `python3` rather than `python` in the
commands below — on these systems a bare `python` is often Python 2, or
missing entirely.

---

## 3. Install NiusBurner

There are two ways in. Pick one.

### Boards Manager (recommended)

NiusBurner is a **boards platform**, so it installs the way platforms do —
not through the Library Manager, which is for C++ libraries a sketch
`#include`s and would reject this on sight.

1. **File → Preferences → Additional Boards Manager URLs**, and add:

   ```
   https://github.com/dunknowcoding/NiusBurner/releases/latest/download/package_niusrobotlab_index.json
   ```

2. **Tools → Board → Boards Manager**, search for `NiusBurner`, and install
   the families you need — 8051, PIC16, PIC18.

That is all. Each platform carries its own copy of the tool, so there is
nothing to clone and no `setup` to run. Python still has to be installed
(§2), but nothing is installed *into* it.

### From a checkout

Better if you want to read the source, change it, or use the command line:

```
git clone https://github.com/dunknowcoding/NiusBurner
cd NiusBurner
python -m niusburner setup
```

`setup` copies the board packages into your sketchbook and records which
Python it ran under. Re-run it whenever you move the folder, change Python,
or pull a newer version.

Either way, **restart the IDE afterwards** — it reads the board list once, at
start-up.

---

## 4. Install the compiler

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

XC8 covers PIC10, PIC12, PIC16 and PIC18 — every part this tool programs.
XC16 (PIC24/dsPIC33) and XC32 (PIC32) are recognised by `detect` if you have
them, but no board here uses them yet; see
[families/pic.md](families/pic.md).

Install to the default location. NiusBurner finds it under the usual
Microchip directories, under `EMBD_TOOLCHAINS`, or under
`C:\embd_toolchains` — or you can record the path yourself:

```bash
python -m niusburner setup --xc8 "C:\Program Files\Microchip\xc8\v3.00\bin\xc8-cc.exe"
```

---

## 5. Install the programmer software and drivers

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

## 6. Wire it up

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

## 7. Set up the Arduino IDE

You already did this in §3, whichever route you took. If you installed from
a checkout, `setup` finds your sketchbook by itself; pass `--sketchbook` only
if you keep it somewhere it would not look:

```bash
python -m niusburner setup --sketchbook "D:\my sketches"
```

Restart the IDE, then:

1. **Tools → Board → NiusBurner 8051 (SDCC)** (or **NiusBurner PIC (XC8)**),
   and pick your part.
2. **Tools → Programmer** — USB-ISP HID for the 8051 parts, PICkit 3 for the
   PIC parts.
3. **Tools → Port** — only needed for the STC parts, which are programmed
   through the serial adapter.

**Verify** compiles. **Upload** erases and programs. There is no third step.

The IDE does not need Python on its PATH and does not need NiusBurner
installed into Python. A checkout install records the interpreter's full
path; a Boards Manager install carries the tool inside the platform. Either
way the board package finds it.

Full menu reference: [arduino-ide.md](arduino-ide.md).

---

## 8. First upload

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
| `Could not find device` from the PIC tools | MPLAB X 6.x or newer. See the warning in §5. |
| The PIC programmer refuses to power the target | The board already has its own supply. Select the plain PICkit 3 entry, not the one that powers the target. |
| Serial output is garbage, or `delay()` is visibly wrong | The board is fitted with a different crystal than the catalog assumes. Set **Tools → Clock**, or `--f-cpu`, to the one actually on the board — it fixes the baud divisor, the delay loops, and on a PIC the oscillator mode too. See [arduino-ide.md](arduino-ide.md#when-the-board-has-a-different-crystal). |
| A PIC programs and verifies but never runs | ICSP is clocked by the programmer, so it works whether or not the target's own oscillator does. Check the crystal and its two load capacitors, and that MCLR has its 10 kΩ pull-up to VDD. |
| `sdcc not found` | Not on `PATH`. Re-run the installer with the PATH option, or `setup --sdcc <path>`. |
| Typing `python` opens the Microsoft Store | That is the Windows placeholder, not Python. See [§2](#2-install-python-windows-first). |
| `python` is not recognised as a command | Python was installed without **Add python.exe to PATH**. Use `py -3` instead, or re-run the installer and tick it. |
| The IDE says it cannot import niusburner, naming a path | A checkout install whose Python or folder moved. Re-run `python -m niusburner setup`, or install through Boards Manager instead, which carries its own copy. |
| It worked from the terminal but not from the IDE | `setup` was run with a different Python than you expected. Check `python -c "import sys; print(sys.executable)"` and re-run `setup` with the one you want. |
| You moved or renamed the NiusBurner folder | Re-run `python -m niusburner setup` from its new location. |
| The Upload button says the part cannot be flashed | That part has no in-circuit programming interface at all; it needs a parallel programming socket. |
| NiusBurner is not in the Library Manager | It is a boards platform, not a library — the Library Manager only lists C++ libraries. Use the Boards Manager URL in [§3](#3-install-niusburner). |
| A part is marked **experimental** | It is in the catalog from its datasheet and family; some of the path is still an assumption. It compiles and sizes correctly — treat the first upload as a test of that. |

`python -m niusburner detect` prints what was found and what was not, which
is usually faster than guessing.
