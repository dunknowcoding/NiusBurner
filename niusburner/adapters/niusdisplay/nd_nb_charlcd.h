/*
 * 8051 bind: NiusCharLCD I2C backpack without linking nd_bus.c.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Arduino Wire is not on this part. SCL is P1.0, SDA is P1.1 (HAL pins 0, 1).
 */

#ifndef ND_NB_CHARLCD_H
#define ND_NB_CHARLCD_H

#include "nd_hd44780.h"

#ifdef __cplusplus
extern "C" {
#endif

nd_result nd_nb_charlcd_begin_i2c(nd_hd44780 *lcd, nd_bus *bus,
                                  nd_u8 cols, nd_u8 rows, nd_u8 addr);

#ifdef __cplusplus
}
#endif

#endif /* ND_NB_CHARLCD_H */
