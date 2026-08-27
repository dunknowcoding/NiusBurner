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

void pinMode(unsigned char pin, unsigned char mode);
void digitalWrite(unsigned char pin, unsigned char value);
unsigned char digitalRead(unsigned char pin);
void delay(unsigned int ms);
void delayMicroseconds(unsigned int us);
unsigned long millis(void);

void setup(void);
void loop(void);

#ifdef __SDCC
#include <8052.h>
#endif

#include "nius_serial.h"

#endif /* NIUS_SKETCH_H */
