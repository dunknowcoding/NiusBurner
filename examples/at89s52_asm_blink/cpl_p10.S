; cpl_p10.S — sdas8051 (ASXXXX) for AT89S52. Not avr-as / GNU as.
;
; Copyright 2026 dunknowcoding (NiusRobotLab)
; SPDX-License-Identifier: Apache-2.0
;
; C prototype: void cpl_p10(void);
; SDCC small-model symbols are prefixed with _. P1.0 is sketch pin 0.

        .module cpl_p10
        .optsdcc -mmcs51 --model-small

        .globl  _cpl_p10

        .area   CSEG (CODE)

P1      = 0x0090

_cpl_p10:
        cpl     P1.0
        ret
