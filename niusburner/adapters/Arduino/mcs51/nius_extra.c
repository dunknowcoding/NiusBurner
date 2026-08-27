/*
 * Arduino helpers that are only worth their flash when a sketch calls them.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * SDCC links whole modules, so anything sharing a translation unit with
 * pinMode() is paid for by every sketch whether it is called or not. On an
 * 8 KB part that is worth a separate file: NiusBurner links this one only
 * when the lowered sketch actually names something in it.
 */

#include "nius_sketch.h"


long map(long value, long from_low, long from_high, long to_low, long to_high)
{
    long span = from_high - from_low;

    if (span == 0)
        return to_low;
    return (value - from_low) * (to_high - to_low) / span + to_low;
}

void shiftOut(unsigned char data_pin, unsigned char clock_pin,
              unsigned char bit_order, unsigned char value)
{
    unsigned char i;

    for (i = 0; i < 8; i++) {
        if (bit_order == LSBFIRST)
            digitalWrite(data_pin, (unsigned char)(value & 1));
        else
            digitalWrite(data_pin, (unsigned char)((value >> 7) & 1));
        value = (unsigned char)(bit_order == LSBFIRST ? value >> 1 : value << 1);
        digitalWrite(clock_pin, HIGH);
        digitalWrite(clock_pin, LOW);
    }
}

unsigned char shiftIn(unsigned char data_pin, unsigned char clock_pin,
                      unsigned char bit_order)
{
    unsigned char i;
    unsigned char value = 0;

    for (i = 0; i < 8; i++) {
        digitalWrite(clock_pin, HIGH);
        if (bit_order == LSBFIRST)
            value = (unsigned char)(value | (digitalRead(data_pin) << i));
        else
            value = (unsigned char)(value | (digitalRead(data_pin) << (7 - i)));
        digitalWrite(clock_pin, LOW);
    }
    return value;
}

/*
 * A 16-bit xorshift. Not Arduino's PRNG and not seeded from noise, but the
 * whole generator is a handful of bytes -- an 8 KB part cannot afford the
 * long-arithmetic one, and a sketch that needs cryptographic randomness is
 * on the wrong chip.
 */
static unsigned int g_rand = 1;

void randomSeed(unsigned long seed)
{
    g_rand = (unsigned int)(seed ? seed : 1);
}

static unsigned int next_rand(void)
{
    g_rand ^= (unsigned int)(g_rand << 7);
    g_rand ^= (unsigned int)(g_rand >> 9);
    g_rand ^= (unsigned int)(g_rand << 8);
    return g_rand;
}

long random(long limit)
{
    if (limit <= 0)
        return 0;
    return (long)(next_rand() % (unsigned int)limit);
}

long randomRange(long low, long high)
{
    if (high <= low)
        return low;
    return low + random(high - low);
}
