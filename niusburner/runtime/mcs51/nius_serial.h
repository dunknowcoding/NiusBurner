/*
 * Arduino Serial on the AT89S52 hardware UART (P3.0 RXD, P3.1 TXD).
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * `python -m niusburner lower` rewrites Serial.begin/print/println/write
 * onto these C functions. This is not HardwareSerial and not printf.
 *
 * 9600 is Timer 1 mode 2 (TH1=0xFD at 11.0592 MHz). 115200 is Timer 2 with
 * RCAP2 = 65536 - Fosc / (32 * baud) (0xFFFD).
 * CH341 USB-TTL: TXD -> P3.0, RXD -> P3.1, GND common, 5 V as the board needs.
 */

#ifndef NIUS_SERIAL_H
#define NIUS_SERIAL_H

#ifndef DEC
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#endif

void nius_serial_begin(unsigned long baud);
void nius_serial_end(void);
void nius_serial_write(unsigned char c);
void nius_serial_flush(void);
unsigned char nius_serial_available(void);
int nius_serial_read(void);

void nius_serial_print_s(const char *s);
void nius_serial_println_s(const char *s);
void nius_serial_println(void);
void nius_serial_print_int(int value, unsigned char base);
void nius_serial_println_int(int value, unsigned char base);

#endif /* NIUS_SERIAL_H */
