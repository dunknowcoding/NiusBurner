/*
 * at89s52_registers — Arduino-shaped sketch that also touches the silicon
 * directly, three ways, in one file.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * This is the floor NiusBurner guarantees on a part with no C++ compiler:
 *
 *   1. Arduino calls          pinMode / digitalWrite / digitalRead / delay
 *   2. Named registers        P1, P3, TMOD, TCON ... straight from <8052.h>
 *   3. Inline assembly        __asm ... __endasm, copied through untouched
 *
 * The translator rewrites the C++ shape of (1) and does not read (2) or (3)
 * at all. An assembly block reaches the compiler byte for byte, so a hand
 * counted delay stays exactly as many cycles as it was written to be.
 *
 *   python -m niusburner upload examples/at89s52_registers --board at89s52 \
 *       --yes --port COM31
 */

/* P1.0 as an Arduino pin, and the same port as a register below. */
#define LED_PIN 0

static unsigned char pattern;

/* Exactly 12 machine cycles, whatever the optimizer does to the rest. */
static void spin12(void) {
  __asm
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
  __endasm;
}

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);

  /* Register write: P3 pins high so they can be read as inputs. Reading a
     port SFR in an expression reads the pin; a compound assignment reads
     the latch. Both spellings survive the translator unchanged. */
  P3 |= 0x10;

  Serial.println(F("registers up"));
  Serial.print(F("TMOD="));
  Serial.println(TMOD, HEX);
}

void loop() {
  /* Arduino API. */
  digitalWrite(LED_PIN, HIGH);
  spin12();
  digitalWrite(LED_PIN, LOW);

  /* The same port, addressed as a register. */
  pattern = (unsigned char)(pattern + 1);
  P1 = (unsigned char)((P1 & 0xF0) | (pattern & 0x0F));

  /* A register read, reported over the UART. */
  if (!(P3 & 0x10)) {
    Serial.println(F("P3.4 low"));
  }

  Serial.print(F("P1="));
  Serial.println(P1, HEX);
  delay(500);
}
