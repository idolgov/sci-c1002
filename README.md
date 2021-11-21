# SCI-C1002 User-driven product development project: Lapsipaimen

![Tests](https://github.com/idolgov/sci-c1002/actions/workflows/test.yaml/badge.svg)

An early prototype of a vibration bracelet for helping parents to stress less
about kids getting lost, developed as part of the SCI-C1002 course of Aalto
University.

## Features

- Startup
  - Short haptic feedback
  - Blink cyan LED once
  - Start connecting or waiting for a connection
  - Device is initially in alert state

- Peripherial device is nearby
  - Blink blue LED every 4-5s
  - Disable haptic alert if it is on

- Peripherial device is too far away
  - Enable haptic alert
  - Blink yellow LED every second

- Action button short press
  - Turn the device on
  - Toggle vibration but don't disable alert state
  - Print device info

- Turn the device off on action button long press

- Calculate approximate distance
  - Distance == 10^((Measured power – RSSI)/(10 * N))
    - Measured power == 1m RSSI of the BLE chip
    - N == environmental factor, 2-4

- Low battery indicator
  - Threshold for low battery currently 3.6 V
  - Blink red LED instead of blue every 4-5s when voltage too low

### TODO

- [ ] Peripheral device: alert when not connected

## Components

- [Adafruit Feather nRF52840 Express][nRF52840]
  * ARM Cortex M4F @64MHz
  * 256KB SRAM
  * nRF52840 BLE
  * RGBW LED
  * LiPo charger
  * UF2 bootloader
  * 51x23x7.2 mm
  * 6 g
- [Adafruit DRV2605L haptic motor controller][DRV2605L]
  * multiple haptic effects
  * 18x17x2 mm
  * 1 g
- [Jinlong Z6SCAB0061141 vibration motor][Z6SCAB0061141]
  * 10000 RPM
  * 14.4x6.8x6.6 mm
  * 0.9 g
- LiPo battery
  * 400mAh
  * 3.7V
  * 35.5x16.6x7.6 mm
  * 8.2 g
- Plastic case
  * ABS
  * 71x71x27 mm
- Tactile push-button
- Lifting wrist straps

[nRF52840]: https://www.adafruit.com/product/4062
[DRV2605L]: https://www.adafruit.com/product/2305
[Z6SCAB0061141]: https://vibration-motor.com/products/cylindrical-vibrator-motors/pcb-mount-thru-hole-vibration-motors/z6scab0061141

## Development

To download and install CircuitPython firmware and required drivers using a
Linux machine plug a device in with a USB cable and run:

    make firmware
    make flash
    
> In case of multiple connected devices define `BOOTLOADER_PATH` env var.

Before uploading new code to the device, check it for formatting and some other
errors, you'll need to create a python virtual environment with dependencies
first:

    make env
    make lint

Now install the code and required libraries on the device:

    make install
    
> In case of multiple connected devices define `CIRCUITPYTHON_PATH` env var.

## License

This project is released using the MIT license.
