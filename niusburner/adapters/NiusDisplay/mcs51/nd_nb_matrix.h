/*
 * 8051 bind: MAX7219 without nd_bus / nd_gfx (those do not fit 8 KB).
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * SPI bit-bang: SCK P1.3, MOSI P1.4. CS is the constructor pin.
 * ISP occupies P1.5/P1.6/P1.7; do not put CS there.
 */

#ifndef ND_NB_MATRIX_H
#define ND_NB_MATRIX_H

#include "nd_hal.h"

#ifndef ND_MAX7219_GENERIC
#define ND_MAX7219_GENERIC 0
#endif
#ifndef ND_MAX7219_FC16
#define ND_MAX7219_FC16 1
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    nd_spi_cfg spi;
    nd_u8 devices;
    nd_u8 wiring;
} nd_nb_matrix;

nd_result nd_nb_matrix_begin(nd_nb_matrix *m, nd_u8 devices, nd_pin cs, nd_u8 wiring);
nd_result nd_nb_matrix_intensity(nd_nb_matrix *m, nd_u8 level);
nd_result nd_nb_matrix_test(nd_nb_matrix *m, nd_u8 on);
nd_result nd_nb_matrix_sleep(nd_nb_matrix *m, nd_u8 on);

#ifdef __cplusplus
}
#endif

#endif /* ND_NB_MATRIX_H */
