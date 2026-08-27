/*
 * Arduino-shaped C for an 8051 sketch that does not pull in NiusDisplay.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pin numbers match the NiusDisplay 8051 HAL so a blink sketch can grow into
 * a display sketch without rewiring: 0..7 are P1.0..P1.7, 8..15 are P2.0..P2.7.
 * ISP occupies P1.5/P1.6/P1.7 while programming; leave those for the dongle.
 */

#ifndef NIUS_SKETCH_H
#define NIUS_SKETCH_H

#define LOW  0
#define HIGH 1
#define INPUT        0
#define OUTPUT       1
#define INPUT_PULLUP 2

#define LSBFIRST 0
#define MSBFIRST 1

/*
 * Arduino spells these as macros, so they are macros here too. That keeps
 * the argument types and the double evaluation identical to what the sketch
 * already does on AVR -- an int-typed function would quietly change the
 * result of min(a, 300) on a char, which is the sort of "equivalent" that
 * is not.
 */
#define bit(b)             (1UL << (b))
#define bitRead(v, b)      (((v) >> (b)) & 1)
#define bitSet(v, b)       ((v) |= (1UL << (b)))
#define bitClear(v, b)     ((v) &= ~(1UL << (b)))
#define bitWrite(v, b, x)  ((x) ? bitSet(v, b) : bitClear(v, b))
#define lowByte(w)         ((unsigned char)((w) & 0xFF))
#define highByte(w)        ((unsigned char)(((w) >> 8) & 0xFF))
#define min(a, b)          ((a) < (b) ? (a) : (b))
#define max(a, b)          ((a) > (b) ? (a) : (b))
#define abs(x)             ((x) > 0 ? (x) : -(x))
#define constrain(x, l, h) ((x) < (l) ? (l) : ((x) > (h) ? (h) : (x)))
#define sq(x)              ((x) * (x))

void pinMode(unsigned char pin, unsigned char mode);
void digitalWrite(unsigned char pin, unsigned char value);
unsigned char digitalRead(unsigned char pin);
void delay(unsigned int ms);
void delayMicroseconds(unsigned int us);

/*
 * Milliseconds spent inside delay(). No timer is started, so this does not
 * advance on its own: a `while (millis() - t < n)` loop that never calls
 * delay() will never finish. That is in docs/translation.md, and it is why
 * micros() is refused outright rather than shipped as a stub.
 */
unsigned long millis(void);

long map(long value, long from_low, long from_high, long to_low, long to_high);
void shiftOut(unsigned char data_pin, unsigned char clock_pin,
              unsigned char bit_order, unsigned char value);
unsigned char shiftIn(unsigned char data_pin, unsigned char clock_pin,
                      unsigned char bit_order);
long random(long limit);
long randomRange(long low, long high);
void randomSeed(unsigned long seed);

void setup(void);
void loop(void);

#ifdef __SDCC
#include <8052.h>
#endif

#include "nius_serial.h"

#endif /* NIUS_SKETCH_H */
