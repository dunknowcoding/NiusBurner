/*
 * niusdisplay_hd44780 — HD44780 PCF8574 backpack with a UART banner.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * BASIC Arduino C++. NiusBurner lowers NiusCharLCD to nd_hd44780_* + bit-banged
 * I2C (P1.0 SCL, P1.1 SDA). USB-ISP flashes; CH341 COM31 is Serial only.
 *
 *   python -m niusburner upload examples/niusdisplay_hd44780 --board at89s52 --yes
 *   python -m niusburner monitor --port COM31 --baud 115200 --seconds 4 --expect "NB HD44780"
 *
 * WIRING
 *   Backpack VCC 5V, GND, SDA -> P1.1, SCL -> P1.0. Address 0x27 (try 0x3F).
 */

#include <NiusDisplay.h>

NiusCharLCD lcd(16, 2, 0x27);

void setup() {
  Serial.begin(115200);
  Serial.println(F("NB HD44780"));
  if (!lcd.begin()) {
    Serial.println(F("INIT_FAIL"));
    return;
  }
  lcd.backlight(true);
  lcd.clear();
  lcd.print("NiusBurner");
  Serial.println(F("INIT_OK"));
}

void loop() {
  Serial.println(F("NB HD44780"));
  delay(500);
}
