/*
 * Software I2C master for classic 8051 parts, shaped like Arduino Wire.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * A classic 8051 has no TWI unit. It does have quasi-bidirectional port
 * pins, which are open-drain when you write 1 to them, so a two-wire bus is
 * exactly what this silicon can fake well: writing 1 releases the line to
 * the pull-up and writing 0 drives it low. That is the whole reason `i2c`
 * is "software" rather than "none" for these boards.
 *
 * Master only, 7-bit addresses, no clock stretching beyond a bounded wait,
 * no multi-master arbitration. Those are in docs/translation.md.
 *
 * Default pins avoid P1.5/P1.6/P1.7, which the ISP header drives:
 *   SCL  P1.0     override with -DNIUS_I2C_SCL_BIT=n
 *   SDA  P1.1     override with -DNIUS_I2C_SDA_BIT=n
 * They match the pins the NiusDisplay 8051 HAL uses, so a sketch can mix
 * Wire with a NiusDisplay I2C device on one bus.
 */

#ifndef NIUS_WIRE_H
#define NIUS_WIRE_H

/* endTransmission() status, same numbering Arduino uses. */
#define NIUS_WIRE_OK        0
#define NIUS_WIRE_ADDR_NACK 2
#define NIUS_WIRE_DATA_NACK 3

#ifndef NIUS_WIRE_RX
#define NIUS_WIRE_RX 8
#endif

void nius_wire_begin(void);
void nius_wire_set_clock(unsigned long hz);
void nius_wire_begin_transmission(unsigned char addr7);
unsigned char nius_wire_write(unsigned char value);
unsigned char nius_wire_end_transmission(void);
unsigned char nius_wire_request_from(unsigned char addr7, unsigned char count);
unsigned char nius_wire_available(void);
int nius_wire_read(void);

#endif /* NIUS_WIRE_H */
