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

/*
 * Printing a number, without throwing away the top of it.
 *
 * Everything used to be forced through `(int)`, which is 16 bits and
 * signed here: Serial.println(millis()) went negative after 32.7 seconds
 * and wrapped to zero after 65.5, and println(70000) printed 4464. No
 * warning in either case, because the cast was in the generated code.
 *
 * C has no overloading, so the type is resolved with _Generic at compile
 * time. Only `unsigned long` needs its own entry; every narrower type
 * converts to `long` without losing a value.
 */
void nius_serial_print_long(long value, unsigned char base);
void nius_serial_println_long(long value, unsigned char base);
void nius_serial_print_ulong(unsigned long value, unsigned char base);
void nius_serial_println_ulong(unsigned long value, unsigned char base);

#define nius_serial_print_num(v, base) _Generic((v),     unsigned long: nius_serial_print_ulong,     default: nius_serial_print_long)((v), (base))

#define nius_serial_println_num(v, base) _Generic((v),     unsigned long: nius_serial_println_ulong,     default: nius_serial_println_long)((v), (base))

#endif /* NIUS_SERIAL_H */
