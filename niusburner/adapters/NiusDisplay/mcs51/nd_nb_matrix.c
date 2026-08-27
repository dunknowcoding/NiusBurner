/*
 * 8051 bind: MAX7219 register writes over bit-banged SPI.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Register map from Maxim MAX7219/MAX7221 (19-4452). One device, or a chain
 * of identical register writes (write_all). No framebuffer, no gfx.
 */

#include "nd_nb_matrix.h"

#ifndef ND_NB_SPI_SCK
#define ND_NB_SPI_SCK 3
#endif
#ifndef ND_NB_SPI_MOSI
#define ND_NB_SPI_MOSI 4
#endif

#define MAX_DIGIT0      0x01
#define MAX_DECODEMODE  0x09
#define MAX_INTENSITY   0x0A
#define MAX_SCANLIMIT   0x0B
#define MAX_SHUTDOWN    0x0C
#define MAX_DISPLAYTEST 0x0F

static nd_result write_all(nd_nb_matrix *m, nd_u8 reg, nd_u8 value)
{
    nd_u8 pair[2];
    nd_u8 i;
    nd_result r;

    pair[0] = reg;
    pair[1] = value;
    nd_hal_gpio_write(m->spi.cs, ND_LOW);
    for (i = 0; i < m->devices; i++) {
        r = nd_hal_spi_write(&m->spi, pair, 2);
        if (r != ND_OK) {
            nd_hal_gpio_write(m->spi.cs, ND_HIGH);
            return r;
        }
    }
    nd_hal_gpio_write(m->spi.cs, ND_HIGH);
    return ND_OK;
}

nd_result nd_nb_matrix_begin(nd_nb_matrix *m, nd_u8 devices, nd_pin cs, nd_u8 wiring)
{
    nd_u8 row;
    nd_result r;

    if (!m || devices == 0) return ND_ERR_PARAM;
    if (cs == ND_PIN_NONE) return ND_ERR_PARAM;

    m->devices = devices;
    m->wiring = wiring;
    m->spi.sck = ND_NB_SPI_SCK;
    m->spi.mosi = ND_NB_SPI_MOSI;
    m->spi.miso = ND_PIN_NONE;
    m->spi.cs = cs;
    m->spi.hz = 0;
    m->spi.mode = ND_SPI_MODE0;
    m->spi.bus_index = 0;

    r = nd_hal_spi_init(&m->spi);
    if (r != ND_OK) return r;
    nd_hal_gpio_config(cs, ND_PIN_OUTPUT);
    nd_hal_gpio_write(cs, ND_HIGH);

    r = write_all(m, MAX_DISPLAYTEST, 0); if (r != ND_OK) return r;
    r = write_all(m, MAX_DECODEMODE, 0);  if (r != ND_OK) return r;
    r = write_all(m, MAX_SCANLIMIT, 7);   if (r != ND_OK) return r;
    r = write_all(m, MAX_INTENSITY, 7);   if (r != ND_OK) return r;
    for (row = 0; row < 8; row++) {
        r = write_all(m, (nd_u8)(MAX_DIGIT0 + row), 0);
        if (r != ND_OK) return r;
    }
    return write_all(m, MAX_SHUTDOWN, 1);
}

nd_result nd_nb_matrix_intensity(nd_nb_matrix *m, nd_u8 level)
{
    if (!m) return ND_ERR_PARAM;
    return write_all(m, MAX_INTENSITY, (nd_u8)(level & 0x0Fu));
}

nd_result nd_nb_matrix_test(nd_nb_matrix *m, nd_u8 on)
{
    if (!m) return ND_ERR_PARAM;
    return write_all(m, MAX_DISPLAYTEST, (nd_u8)(on ? 1 : 0));
}

nd_result nd_nb_matrix_sleep(nd_nb_matrix *m, nd_u8 on)
{
    if (!m) return ND_ERR_PARAM;
    return write_all(m, MAX_SHUTDOWN, (nd_u8)(on ? 0 : 1));
}
