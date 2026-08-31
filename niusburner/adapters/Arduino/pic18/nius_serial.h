/*
 * Serial on the PIC16 USART.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * RC6 is TX and RC7 is RX. Those two pins stop being general-purpose I/O
 * once Serial.begin() runs, which is why the pin table in nius_sketch.h
 * calls them out.
 *
 * Printing a number keeps its width. C has no overloading, so the type is
 * resolved with _Generic: only `unsigned long` needs its own routine and
 * everything narrower converts to `long` without losing a value. Casting
 * everything to `int` the way a naive port does would make
 * Serial.println(millis()) go negative after 32.7 seconds.
 */

#ifndef NIUS_SERIAL_H
#define NIUS_SERIAL_H

#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2

void nius_serial_begin(unsigned long baud);
void nius_serial_end(void);
void nius_serial_write(unsigned char value);
void nius_serial_flush(void);
unsigned char nius_serial_available(void);
int nius_serial_read(void);

void nius_serial_print_s(const char *s);
void nius_serial_println_s(const char *s);
void nius_serial_println(void);
void nius_serial_print_int(int value, unsigned char base);
void nius_serial_println_int(int value, unsigned char base);

void nius_serial_print_long(long value, unsigned char base);
void nius_serial_println_long(long value, unsigned char base);
void nius_serial_print_ulong(unsigned long value, unsigned char base);
void nius_serial_println_ulong(unsigned long value, unsigned char base);

/*
 * XC8's PIC16 back end rejects _Generic outright -- 'error in backend:
 * unknown expression type' -- so the type is resolved with __typeof__
 * instead, which it accepts. (SDCC is the other way round and takes
 * _Generic but not __typeof__, which is why the two families do not
 * share this header.)
 *
 * Both arms are void and the condition is a compile-time constant, so
 * the dead one is dropped and there is no runtime test. The value
 * appears in one arm only, so an argument with a side effect happens
 * exactly once.
 */
/*
 * The width test is a compile-time constant, so XC8 drops the branch it
 * does not need and then warns (759) that the line generated no code --
 * once per print, in the sketch's own file, about something the sketch
 * did not write. Disabled here for that reason and no other.
 */
#pragma warning disable 759

#define NIUS_IS_UNSIGNED(v) ((__typeof__(v))-1 > (__typeof__(v))0)

#define nius_serial_print_num(v, base) do {                      \
    if (NIUS_IS_UNSIGNED(v) && sizeof(v) >= 4)                    \
        nius_serial_print_ulong((unsigned long)(v), (base));      \
    else                                                          \
        nius_serial_print_long((long)(v), (base));                \
} while (0)

#define nius_serial_println_num(v, base) do {                    \
    if (NIUS_IS_UNSIGNED(v) && sizeof(v) >= 4)                    \
        nius_serial_println_ulong((unsigned long)(v), (base));    \
    else                                                          \
        nius_serial_println_long((long)(v), (base));              \
} while (0)

#endif /* NIUS_SERIAL_H */
