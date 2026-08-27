/*
 * 8051 bind: HD44780 PCF8574 backpack via bit-banged I2C.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Fills nd_bus.cfg.i2c and calls nd_hal_i2c_* / nd_hd44780_init. Does not
 * reference nd_bus_i2c_setup, so SDCC does not pull the whole bus module.
 */

#include "nd_nb_charlcd.h"
#include "nd_hal.h"

#ifndef ND_NB_I2C_SCL
#define ND_NB_I2C_SCL 0
#endif
#ifndef ND_NB_I2C_SDA
#define ND_NB_I2C_SDA 1
#endif

nd_result nd_nb_charlcd_begin_i2c(nd_hd44780 *lcd, nd_bus *bus,
                                  nd_u8 cols, nd_u8 rows, nd_u8 addr)
{
    nd_hd44780_cfg cfg;

    if (!lcd || !bus) return ND_ERR_PARAM;
    if (cols == 0 || rows == 0) return ND_ERR_PARAM;

    bus->vt = 0;
    bus->kind = ND_BUS_I2C;
    bus->dc = ND_PIN_NONE;
    bus->rst = ND_PIN_NONE;
    bus->bl = ND_PIN_NONE;
    bus->user = 0;
    bus->cfg.i2c.sda = ND_NB_I2C_SDA;
    bus->cfg.i2c.scl = ND_NB_I2C_SCL;
    bus->cfg.i2c.hz = 0;
    bus->cfg.i2c.addr = addr;
    bus->cfg.i2c.bus_index = 0;

    if (nd_hal_i2c_init(&bus->cfg.i2c) != ND_OK)
        return ND_ERR_BUS;

    cfg.cols = cols;
    cfg.rows = rows;
    cfg.wiring = ND_HD44780_I2C_PCF8574;
    cfg.rs = cfg.en = cfg.d4 = cfg.d5 = cfg.d6 = cfg.d7 = ND_PIN_NONE;
    cfg.backlight = ND_PIN_NONE;
    return nd_hd44780_init(lcd, bus, &cfg);
}
