/*
 * The Arduino API, as C, for a mid-range PIC16.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pin numbering is the port number times eight plus the bit, so the number
 * and the datasheet name convert in your head:
 *
 *    0- 7  RA0-RA7      (RA0-RA5 exist on a 16F877A)
 *    8-15  RB0-RB7
 *   16-23  RC0-RC7      RC6 and RC7 are the USART when Serial is used
 *   24-31  RD0-RD7
 *   32-34  RE0-RE2
 *
 * Direction is a TRIS bit, inverted from what the name suggests: 0 drives
 * the pin, 1 releases it to be read. pinMode() hides that.
 *
 * PORTA and PORTE come out of reset as analog inputs, and reading them
 * digitally returns zero until ADCON1 says otherwise. The generated main()
 * sets ADCON1 before setup() runs, so a sketch that never mentions the ADC
 * still gets working digital pins on those ports.
 */

#ifndef NIUS_SKETCH_H
#define NIUS_SKETCH_H

#include <xc.h>

#define LOW  0
#define HIGH 1
#define INPUT        0
#define OUTPUT       1
#define INPUT_PULLUP 2

#define LSBFIRST 0
#define MSBFIRST 1

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
 * RB0 by convention: the first pin of the port most 16F877A boards put
 * their LEDs on. Override it for a board that does not.
 */
#ifndef LED_BUILTIN
#define LED_BUILTIN 8
#endif

#ifndef static_assert
#define static_assert _Static_assert
#endif

#define PI         3.1415926535897932384626433832795
#define HALF_PI    1.5707963267948966192313216916398
#define TWO_PI     6.283185307179586476925286766559
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define EULER      2.718281828459045235360287471352

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
unsigned long millis(void);

long map(long value, long from_low, long from_high, long to_low, long to_high);
void shiftOut(unsigned char data_pin, unsigned char clock_pin,
              unsigned char bit_order, unsigned char value);
unsigned char shiftIn(unsigned char data_pin, unsigned char clock_pin,
                      unsigned char bit_order);
long random(long range);
long randomRange(long low, long high);
void randomSeed(unsigned long seed);

void setup(void);
void loop(void);

#endif /* NIUS_SKETCH_H */
