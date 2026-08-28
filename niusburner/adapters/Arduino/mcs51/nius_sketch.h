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

/*
 * The Arduino spellings a sketch expects to already exist. Each is exactly
 * the AVR core's definition, because a different one is a silent behaviour
 * change: `_BV` shifts an int there, so it shifts an int here too.
 */
#include <string.h>              /* memcpy, memset, strlen, strcmp */
#include <stdio.h>               /* sprintf, if a sketch wants it */

typedef unsigned char byte;
typedef unsigned int  word;

#ifndef NULL
#define NULL ((void *)0)
#endif
#define nullptr NULL

#define _BV(b) (1 << (b))

/*
 * P1.0 by convention: it is where 8051 development boards put their first
 * LED. Override it for a board that does not, and note that this is a
 * convention rather than something the silicon defines.
 */
#ifndef LED_BUILTIN
#define LED_BUILTIN 0
#endif

/*
 * The maths constants. Defined so a sketch that only names them compiles;
 * actually doing float arithmetic with them still costs the soft-float
 * library, which is why the float maths functions stay refused.
 */
#define PI         3.1415926535897932384626433832795
#define HALF_PI    1.5707963267948966192313216916398
#define TWO_PI     6.283185307179586476925286766559
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define EULER      2.718281828459045235360287471352

/* C11 spelling of a compile-time check; SDCC accepts the underscore form
   even under --std-c99. */
#ifndef static_assert
#define static_assert _Static_assert
#endif

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
