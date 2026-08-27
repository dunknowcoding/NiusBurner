/*
 * niusdisplay_max7219 — MAX7219 display-test with a UART banner.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * BASIC Arduino C++. Lowered to nd_max7219_* without the gfx/font stack
 * (that stack does not fit 8 KB). USB-ISP flashes; CH341 COM31 is Serial only.
 *
 *   python -m niusburner upload examples/niusdisplay_max7219 --board at89s52 --yes
 *   python -m niusburner monitor --port COM31 --baud 115200 --seconds 4 --expect "NB MAX7219"
 *
 * WIRING (8051 HAL pin N is P1.N). ISP occupies P1.5/P1.6/P1.7.
 *   MAX7219 CLK  -> P1.3
 *   MAX7219 DIN  -> P1.4
 *   MAX7219 CS   -> P1.2  (constructor pin 2)
 *   VCC, GND
 */

#include <NiusDisplay.h>

NiusMatrix matrix(1, 2, ND_MAX7219_GENERIC);

void setup() {
  Serial.begin(115200);
  Serial.println(F("NB MAX7219"));
  if (!matrix.begin()) {
    Serial.println(F("INIT_FAIL"));
    return;
  }
  matrix.setIntensity(3);
  matrix.testAll(1);
  Serial.println(F("INIT_OK"));
}

void loop() {
  Serial.println(F("NB MAX7219"));
  delay(500);
}
