/*
 * Software SPI master for classic 8051 parts, shaped like Arduino SPI.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * A classic 8051 has no SPI unit. The SPI-looking pins on the ISP header
 * belong to the serial programming state machine and are not usable as a
 * peripheral from running code, so a three-wire master is bit-banged. All
 * four modes and both bit orders are implemented, because getting CPOL or
 * CPHA wrong silently returns the wrong bits rather than failing.
 *
 * Master only, no slave select handling (drive your own CS with
 * digitalWrite, exactly as an Arduino sketch does), no interrupts.
 *
 * Default pins keep clear of P1.5/P1.6/P1.7, which the ISP header drives,
 * and match the pins the NiusDisplay 8051 HAL uses:
 *   SCK   P1.3    -DNIUS_SPI_SCK_BIT=n
 *   MOSI  P1.4    -DNIUS_SPI_MOSI_BIT=n
 *   MISO  P1.2    -DNIUS_SPI_MISO_BIT=n
 */

#ifndef NIUS_SPI_H
#define NIUS_SPI_H

#define NIUS_SPI_MSBFIRST 1
#define NIUS_SPI_LSBFIRST 0

/*
 * Arduino's SPI_MODEn and SPI_CLOCK_DIVn are AVR SPCR/SPSR bit patterns, not
 * 0..3 and not the divisor. Keeping the same numbers means a sketch written
 * against the Arduino SPI library passes the constants it already uses.
 */
#ifndef SPI_MODE0
#define SPI_MODE0 0x00
#define SPI_MODE1 0x04
#define SPI_MODE2 0x08
#define SPI_MODE3 0x0C
#endif

#ifndef SPI_CLOCK_DIV4
#define SPI_CLOCK_DIV4   0x00
#define SPI_CLOCK_DIV16  0x01
#define SPI_CLOCK_DIV64  0x02
#define SPI_CLOCK_DIV128 0x03
#define SPI_CLOCK_DIV2   0x04
#define SPI_CLOCK_DIV8   0x05
#define SPI_CLOCK_DIV32  0x06
#endif

void nius_spi_begin(void);
void nius_spi_end(void);
void nius_spi_set_bit_order(unsigned char msb_first);
void nius_spi_set_data_mode(unsigned char mode);      /* 0..3 */
void nius_spi_set_clock_divider(unsigned char divider);
unsigned char nius_spi_transfer(unsigned char value);

#endif /* NIUS_SPI_H */
