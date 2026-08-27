/*
 * at89s52_serial — Arduino-shaped UART sketch for the AT89S52.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * This is the same shape as an Arduino IDE sketch: setup(), loop(),
 * Serial.begin/println, pinMode/digitalWrite. SDCC has no C++; NiusBurner
 * rewrites Serial onto the hardware UART (P3.0 RXD, P3.1 TXD).
 *
 * CH341 USB-TTL, 5 V:
 *   CH341 TXD -> MCU RXD  (P3.0, DIP-40 pin 10)
 *   CH341 RXD -> MCU TXD  (P3.1, DIP-40 pin 11)
 *   CH341 GND -> GND
 *   CH341 5V  -> VCC if the board is powered from the adapter
 *
 * Crystal must be 11.0592 MHz or 9600 baud will be wrong.
 * USB-ISP (HID) flashes the chip; the CH341 is only the serial console.
 *
 *   python -m niusburner upload examples/at89s52_serial --board at89s52 --yes
 *   python -m niusburner monitor --port COM31 --baud 9600
 */

void setup() {
  Serial.begin(9600);
  pinMode(0, OUTPUT);
  Serial.println("AT89S52 serial");
}

void loop() {
  Serial.println("tick");
  digitalWrite(0, HIGH);
  delay(500);
  digitalWrite(0, LOW);
  delay(500);
}
