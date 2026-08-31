/*
 * Enter the STC bootloader from a running sketch, on request from the host.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * An STC89 enters its bootloader on power-on and on nothing else. There is
 * no pin to assert, a reset pin that re-enters user code rather than the
 * bootloader, and no way to interrupt the supply under software control.
 * That leaves one door, and the part provides it: ISP_CONTR at 0xE7 carries SWBS and SWRST, and writing both
 * performs a reset that boots from the ISP block rather than from user
 * code. That is a bootloader entry a running program can perform on
 * itself.
 *
 * So the host asks. A magic byte sequence arriving on the UART means "go to
 * the bootloader", and the sketch obliges. The cost is one interrupt: the
 * sequence has to be noticed whatever the sketch is doing, and a sketch
 * that never reads Serial would never see it otherwise.
 *
 * The interrupt is why this is opt-in rather than always on. An ISR fires
 * inside delay() and inside every bit-banged bus transfer, and this tool
 * refuses to retime a sketch without being asked. Build with
 * NIUS_ISP_ENTRY defined -- Tools > Bootloader entry in the IDE -- and the
 * first upload after that is the last one that needs a hand on the power.
 *
 * The sequence is long and unlikely on purpose: a sketch that happens to
 * receive it would reset into the bootloader, which is a bad surprise.
 */

#include "nius_sketch.h"
#include "nius_serial.h"

#ifdef NIUS_ISP_ENTRY
#ifdef __SDCC

#include <8052.h>

/* STC89 In-System-Programming control. Not in <8052.h>: it is an STC
   addition, at 0xE7 on this generation. */
__sfr __at(0xE7) NIUS_ISP_CONTR;

/* SWBS selects the ISP block as the boot source, SWRST performs the reset.
   Both together is "reset into the bootloader"; SWRST alone restarts user
   code, which is not what is wanted here. */
#define NIUS_SWBS 0x40
#define NIUS_SWRST 0x20

/* Seventeen bytes, none of them plausible traffic. */
static const unsigned char MAGIC[] = {
    'N', 'B', 0x1B, 'I', 'S', 'P', 0x1B, 'E', 'N', 'T', 'R', 'Y',
    0x1B, 0xA5, 0x5A, 0xA5, 0x5A,
};
#define MAGIC_LEN (sizeof MAGIC / sizeof MAGIC[0])

static unsigned char g_matched;

/*
 * The transmitter is polled, and the serial interrupt fires for both
 * directions, so the ISR has to take responsibility for TI as well: left
 * set it would re-enter the ISR forever, and cleared without a record the
 * polled writer would wait for an event that already happened. It is
 * recorded here and nius_serial_write() waits on the record instead.
 */
volatile unsigned char nius_tx_done = 1;

void nius_isp_entry_isr(void) __interrupt(4)
{
    if (RI) {
        unsigned char c = SBUF;

        RI = 0;
        if (c == MAGIC[g_matched]) {
            g_matched++;
            if (g_matched >= MAGIC_LEN) {
                /* Nothing after this line runs: the write resets the part
                   into the ISP block, where the bootloader is waiting. */
                NIUS_ISP_CONTR = NIUS_SWBS | NIUS_SWRST;
            }
        } else {
            /* Restart the match, allowing for the byte that broke it being
               the start of a fresh attempt. */
            g_matched = (unsigned char)(c == MAGIC[0] ? 1 : 0);
        }
    }
    if (TI) {
        TI = 0;
        nius_tx_done = 1;
    }
}

void nius_isp_entry_begin(void)
{
    g_matched = 0;
    nius_tx_done = 1;
    ES = 1;                 /* serial interrupt */
    EA = 1;                 /* global enable */
}

#endif /* __SDCC */
#endif /* NIUS_ISP_ENTRY */
