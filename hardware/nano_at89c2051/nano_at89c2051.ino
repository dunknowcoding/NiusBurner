/*
 * AT89C2051 programmer, hosted on an Arduino Nano V3.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * WHY THIS EXISTS: the AT89C2051 has no ISP. Unlike its AT89S52 sibling it
 * cannot be reached by a USBasp or any SPI programmer, because it has no
 * serial programming interface at all. It is programmed by a 12 V parallel
 * algorithm, and that is what this sketch implements.
 *
 * THE ONE THING THAT MAKES THIS CHIP ODD: there is no address bus. The
 * internal address counter is RESET by taking RST low, and ADVANCED by a
 * pulse on XTAL1. So programming is strictly sequential from address 0 --
 * you cannot seek. Every byte must be written in order, and a re-write of one
 * byte means walking the counter there again.
 *
 * WIRING (Nano -> AT89C2051 DIP20)
 *
 *   Nano D2..D9   -> P1.0..P1.7   pins 12..19   data bus
 *   Nano D10      -> XTAL1        pin 5         address counter advance
 *   Nano D11      -> P3.2 /PROG   pin 6         program pulse
 *   Nano D12      -> P3.3         pin 7    \
 *   Nano D13      -> P3.4         pin 8     |  mode select
 *   Nano A0       -> P3.5         pin 9     |
 *   Nano A1       -> P3.7         pin 11   /
 *   Nano A2       -> VPP_EN       (drives the 12 V switch onto RST pin 1)
 *   Nano A3       -> VIH_EN       (drives 5 V onto RST pin 1)
 *   Nano 5V/GND   -> VCC pin 20 / GND pin 10
 *
 * THE 12 V RAIL IS NOT OPTIONAL and the Nano cannot produce it. RST/VPP needs
 * 12 V during programming and erase. Use a small boost module or a 12 V supply
 * switched by a transistor; A2 drives that switch and A3 drives a plain 5 V
 * path for the modes that want VIH rather than VPP.
 *
 * NEVER assert both A2 and A3 at once -- that shorts 12 V into the 5 V rail
 * and will destroy the Nano. assertRst() below is written so that cannot
 * happen from software.
 */

#include <Arduino.h>

// ---- pin map ---------------------------------------------------------
static const uint8_t P1[8] = { 2, 3, 4, 5, 6, 7, 8, 9 };
#define PIN_XTAL1   10
#define PIN_PROG    11
#define PIN_P33     12
#define PIN_P34     13
#define PIN_P35     A0
#define PIN_P37     A1
#define PIN_VPP_EN  A2
#define PIN_VIH_EN  A3

// AT89C2051: 2 KB of flash. Nothing here may address beyond it.
#define FLASH_SIZE  2048

// ---- RST/VPP ---------------------------------------------------------

enum RstLevel { RST_LOW, RST_VIH, RST_VPP };

/*
 * The only function that touches the two enables. Both are driven low before
 * either is driven high, so the 12 V and 5 V paths can never be on together
 * however the caller sequences things.
 */
static void assertRst(RstLevel level) {
  digitalWrite(PIN_VPP_EN, LOW);
  digitalWrite(PIN_VIH_EN, LOW);
  delayMicroseconds(50);          // let the rail settle before switching

  if (level == RST_VIH) digitalWrite(PIN_VIH_EN, HIGH);
  else if (level == RST_VPP) digitalWrite(PIN_VPP_EN, HIGH);
  delayMicroseconds(50);
}

// ---- data bus --------------------------------------------------------

static void busOutput(uint8_t value) {
  for (uint8_t i = 0; i < 8; i++) {
    pinMode(P1[i], OUTPUT);
    digitalWrite(P1[i], (value >> i) & 1);
  }
}

static void busInput(void) {
  // No pull-ups: P1 on this part has its own, and adding the Nano's would
  // fight them and read back a stuck-high bus.
  for (uint8_t i = 0; i < 8; i++) pinMode(P1[i], INPUT);
}

static uint8_t busRead(void) {
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++)
    if (digitalRead(P1[i])) v |= (1 << i);
  return v;
}

// ---- mode select -----------------------------------------------------
/*
 * From the AT89C2051 datasheet's programming-mode table. These four lines
 * select what a PROG pulse does; getting one wrong silently performs a
 * different operation, which is why they are named rather than inlined.
 */
static void setMode(bool p33, bool p34, bool p35, bool p37) {
  digitalWrite(PIN_P33, p33);
  digitalWrite(PIN_P34, p34);
  digitalWrite(PIN_P35, p35);
  digitalWrite(PIN_P37, p37);
  delayMicroseconds(10);
}

#define MODE_WRITE_CODE()  setMode(LOW,  HIGH, HIGH, HIGH)
#define MODE_READ_CODE()   setMode(HIGH, HIGH, HIGH, HIGH)
#define MODE_ERASE()       setMode(LOW,  LOW,  HIGH, HIGH)
#define MODE_LOCK1()       setMode(HIGH, HIGH, HIGH, LOW)
#define MODE_LOCK2()       setMode(HIGH, HIGH, LOW,  LOW)
#define MODE_SIGNATURE()   setMode(LOW,  LOW,  LOW,  LOW)

// ---- address counter -------------------------------------------------

/*
 * There is no address bus. The counter resets when RST goes low and advances
 * one position per XTAL1 pulse, so all access is sequential from zero.
 */
static void addrReset(void) {
  assertRst(RST_LOW);
  digitalWrite(PIN_XTAL1, LOW);
  delayMicroseconds(100);
  assertRst(RST_VIH);
}

static void addrNext(void) {
  digitalWrite(PIN_XTAL1, HIGH);
  delayMicroseconds(2);
  digitalWrite(PIN_XTAL1, LOW);
  delayMicroseconds(2);
}

// ---- operations ------------------------------------------------------

static void progPulse(uint16_t microseconds) {
  digitalWrite(PIN_PROG, LOW);
  if (microseconds > 16000) delay(microseconds / 1000);
  else delayMicroseconds(microseconds);
  digitalWrite(PIN_PROG, HIGH);
}

static void chipErase(void) {
  addrReset();
  MODE_ERASE();
  assertRst(RST_VPP);
  progPulse(12000);          // 10 ms minimum; 12 gives margin
  assertRst(RST_VIH);
}

static bool writeByte(uint8_t value) {
  busOutput(value);
  MODE_WRITE_CODE();
  assertRst(RST_VPP);
  progPulse(110);            // 1..110 us per the datasheet
  assertRst(RST_VIH);
  delayMicroseconds(50);     // write cycle time before the next access
  return true;
}

static uint8_t readByte(void) {
  busInput();
  MODE_READ_CODE();
  delayMicroseconds(10);
  return busRead();
}

static uint8_t hexVal(char c);

// ---- host protocol ---------------------------------------------------
/*
 * Deliberately line-based text rather than a binary protocol. It can be driven
 * from a serial terminal by hand when something is wrong, which matters a lot
 * for a part with no debug interface whatsoever.
 */

static void cmdSignature(void) {
  addrReset();
  busInput();
  MODE_SIGNATURE();
  delayMicroseconds(10);
  uint8_t a = busRead();
  addrNext();
  uint8_t b = busRead();

  Serial.print(F("SIG "));
  if (a < 16) Serial.print('0');
  Serial.print(a, HEX);
  Serial.print(' ');
  if (b < 16) Serial.print('0');
  Serial.println(b, HEX);

  // 1E 21 is Atmel / AT89C2051. Anything else means the wiring, the 12 V rail
  // or the part itself is wrong, and writing would be pointless.
  if (a == 0x1E && b == 0x21) Serial.println(F("OK AT89C2051"));
  else Serial.println(F("ERR unexpected signature"));
}

static void cmdRead(uint16_t count) {
  if (count > FLASH_SIZE) count = FLASH_SIZE;
  addrReset();
  for (uint16_t i = 0; i < count; i++) {
    uint8_t v = readByte();
    if (v < 16) Serial.print('0');
    Serial.print(v, HEX);
    if ((i & 31) == 31) Serial.println();
    addrNext();
  }
  Serial.println();
  Serial.println(F("OK"));
}

/*
 * Write is streamed: the host sends hex byte pairs and this walks the counter
 * forward as it goes, because seeking is impossible. Each byte is verified
 * immediately -- a failure 1500 bytes in is worth knowing about before the
 * remaining 500 are written.
 */
static void cmdWrite(uint16_t count) {
  if (count > FLASH_SIZE) {
    Serial.println(F("ERR too large for 2 KB"));
    return;
  }
  addrReset();
  Serial.println(F("RDY"));

  for (uint16_t i = 0; i < count; i++) {
    while (Serial.available() < 2) { /* wait for the pair */ }
    char hi = Serial.read(), lo = Serial.read();
    uint8_t v = (uint8_t)((hexVal(hi) << 4) | hexVal(lo));

    writeByte(v);

    uint8_t back = readByte();
    if (back != v) {
      Serial.print(F("ERR verify at "));
      Serial.print(i);
      Serial.print(F(" wrote "));
      Serial.print(v, HEX);
      Serial.print(F(" read "));
      Serial.println(back, HEX);
      return;
    }
    addrNext();
  }
  Serial.println(F("OK"));
}

static uint8_t hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return 0;
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_VPP_EN, OUTPUT);
  pinMode(PIN_VIH_EN, OUTPUT);
  digitalWrite(PIN_VPP_EN, LOW);
  digitalWrite(PIN_VIH_EN, LOW);

  pinMode(PIN_XTAL1, OUTPUT);
  pinMode(PIN_PROG, OUTPUT);
  pinMode(PIN_P33, OUTPUT);
  pinMode(PIN_P34, OUTPUT);
  pinMode(PIN_P35, OUTPUT);
  pinMode(PIN_P37, OUTPUT);

  digitalWrite(PIN_XTAL1, LOW);
  digitalWrite(PIN_PROG, HIGH);   // PROG is active low; idle high
  busInput();

  Serial.println(F("AT89C2051 programmer ready"));
  Serial.println(F("cmds: S=signature  E=erase  Rnnnn=read  Wnnnn=write"));
}

void loop() {
  if (!Serial.available()) return;

  char c = Serial.read();
  switch (c) {
  case 'S': cmdSignature(); break;
  case 'E': chipErase(); Serial.println(F("OK erased")); break;
  case 'R': cmdRead((uint16_t)Serial.parseInt()); break;
  case 'W': cmdWrite((uint16_t)Serial.parseInt()); break;
  case '\r': case '\n': break;
  default: Serial.println(F("ERR unknown command")); break;
  }
}
