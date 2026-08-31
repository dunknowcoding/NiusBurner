; toggle_rb2 — flip RB2, in one instruction.
;
; Copyright 2026 dunknowcoding (NiusRobotLab)
; SPDX-License-Identifier: Apache-2.0
;
; A C function named toggle_rb2 is _toggle_rb2 here. PSECT declares the
; section the linker places; delta=2 says the addresses are word-addressed,
; which is what program memory on a mid-range PIC is.

    GLOBAL  _toggle_rb2
    PSECT   text_toggle,local,class=CODE,delta=2

_toggle_rb2:
    MOVLW   0x04            ; bit 2
    XORWF   6, 1            ; PORTB lives at 0x06 in bank 0
    RETURN
