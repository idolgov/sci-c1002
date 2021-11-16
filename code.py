"""Lapsipaimen proto based on Adafruit Feather M0 Express.

Features:

- Startup
  - Short haptic feedback
  - Blink cyan LED once
  - Start connecting or waiting for BLE connection

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

TODO:

- Implement lower and upper thresholds for RSSI/distance
  - ATM alerts are too sensitive near the single threshold
  - use lower one when alert is on and higher one when it is off

- Implement low battery alert
  - Test what is a good threshold for a 3.7V battery
  - Blink red LED instead of blue every 4-5s when voltage too low

- Calculate distance instead of just measuring RSSI
  - Distance == 10^((Measured power – RSSI)/(10 * N))
    - Measured power == 1m RSSI of the BLE chip
    - N == environmental factor, 2-4

- Try decreasing connection and advertising intervals to improve
  RSSI accuracy and stability
  - connection.connection_interval can be x*1.25
  
- Always alert when not connected
"""

import time
import os
import gc
import binascii

# pylint: disable=import-error
import board
import microcontroller
import alarm
import busio
from digitalio import DigitalInOut, Direction, Pull
from analogio import AnalogIn
import neopixel
import adafruit_drv2605
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

# Haptic effects
# Refer to table 11.2 in the datasheet:
# http://www.ti.com/lit/ds/symlink/drv2605.pdf
HAPTIC_EFFECT_NOTIFY = 47
HAPTIC_EFFECT_NOTIFY_LEVEL = 80
HAPTIC_EFFECT_ALERT = 58
HAPTIC_EFFECT_ALERT_LEVEL = 100
HAPTIC_EFFECT_ALERT_SECONDS = 1

BTN = board.D6
BTN_LONG_PRESS_SECONDS = 8

COLOR_OFF = "off"
COLOR_BLUE = "blue"
COLOR_GREEN = "green"
COLOR_CYAN = "cyan"
COLOR_PURPLE = "purple"
COLOR_RED = "red"
COLOR_YELLOW = "yellow"
COLORS = {
    COLOR_OFF: (0, 0, 0),
    COLOR_BLUE: (0, 0, 255),
    COLOR_GREEN: (0, 255, 0),
    COLOR_CYAN: (0, 255, 255),
    COLOR_PURPLE: (180, 0, 255),
    COLOR_RED: (255, 0, 0),
    COLOR_YELLOW: (255, 150, 0),
}

BLE_MAC_CENTRAL = "f4:a7:b4:0b:c7:36"
BLE_MAC_PERIPHERAL = "e2:6d:58:bd:ec:4b"
BLE_RSSI_THRESHOLD = -80

LED_STATUS_SECONDS = 5

# Initialize I2C bus
# pylint: disable=invalid-name
i2c = busio.I2C(board.SCL, board.SDA)
# Initialize haptic driver
drv = adafruit_drv2605.DRV2605(i2c)
# Initialize ble mode input
d5 = DigitalInOut(board.D5)
d5.direction = Direction.INPUT
d5.pull = Pull.UP
# Initialize main button
btn = DigitalInOut(BTN)
btn.direction = Direction.INPUT
btn.pull = Pull.UP
# Initialize lipo monitor
lipo_voltage_raw = AnalogIn(board.VOLTAGE_MONITOR)
# Initialize neopixel
pixels = neopixel.NeoPixel(board.NEOPIXEL, 1)
# Initialize ble
ble = BLERadio()

ble_is_central = d5.value
ble_connection = None
ble_rssi = []
btn_state = btn.value
btn_timestamp = 0
alert_state = False
alert_timestamp = 0
silent = False
status_timestamp = time.monotonic()

if not ble_is_central:
    uart = UARTService()
    advertisement = ProvideServicesAdvertisement(uart)


def vibrate(effect=HAPTIC_EFFECT_NOTIFY, level=HAPTIC_EFFECT_NOTIFY_LEVEL):
    """Play a given haptic effect at a given level.

    Possible levels: 20, 40, 60, 80 and 100%.
    """
    effect = int(HAPTIC_EFFECT_ALERT + 5 - level / 20)
    drv.sequence[0] = adafruit_drv2605.Effect(effect)

    print(f"Playing haptic effect {effect} at {level}%...")

    drv.play()


def blink(color, duration=0.5, count=1):
    """Flash neopixel led.

    Duration in seconds for a single blink.
    """
    for i in range(count):
        pixels[0] = COLORS[color]
        time.sleep(duration)
        pixels[0] = COLORS[COLOR_OFF]

        # Don't wait after the last loop
        if i != count - 1:
            time.sleep(duration)


def bytes_to_mac(addr_bytes):
    """Convert address bytes to MAC."""
    return ":".join(f"{b:02x}" for b in reversed(addr_bytes))


def connect():
    """Try to connect to a peripheral device.

    We only connect to a device when it is too far away or has just
    returned into allowed radius in order to trigger or dismiss an
    alert.
    """
    # print(f"Connecting...")

    global ble_rssi, alert_state
    connection = None

    for adv in ble.start_scan(
        ProvideServicesAdvertisement, timeout=1, minimum_rssi=-100
    ):
        if UARTService not in adv.services:
            continue

        addr = bytes_to_mac(adv.address.address_bytes)
        ble_rssi.append(adv.rssi)
        if len(ble_rssi) > 10:
            ble_rssi.pop(0)
        mean_rssi = 0
        for i in ble_rssi:
            mean_rssi = mean_rssi + i
        mean_rssi = mean_rssi / len(ble_rssi)

        if addr != BLE_MAC_PERIPHERAL:
            continue

        # Our peripheral device is too far away!
        if mean_rssi and mean_rssi < BLE_RSSI_THRESHOLD:
            # Alert was not in effect
            if not alert_state:
                alert_state = True
                connection = ble.connect(adv)
                print(f"Connected to {addr}")
                break
        # Our peripheral device is back!
        else:
            # We need to infor the device that alert is over
            if alert_state:
                alert_state = False
                try:
                    connection = ble.connect(adv)
                    print(f"Connected to {addr}")
                except:
                    print("Connection failed")
                    ble_rssi = []
                break

    ble.stop_scan()

    if not connection:
        return

    # Send own MAC address and alert state
    try:
        uart = connection[UARTService]  # pylint: disable=redefined-outer-name
        uart.write(ble._adapter.address.address_bytes)
        time.sleep(0.2)
        print(f"Sending alert state: {alert_state}")
        uart.write(str(int(alert_state)).encode("utf-8"))
    except:
        print("Connection failed!")
        ble_rssi = []
    finally:
        connection.disconnect()


def wait_for_connection():
    """Wait for a connection from a central device."""
    global alert_state

    # print(f"Connecting...")

    if not ble._adapter.advertising:
        ble.start_advertising(advertisement)

    if not ble.connected:
        time.sleep(0.5)
        return

    # Receive MAC address of the central
    addr = bytes_to_mac(uart.read(6))

    if addr == BLE_MAC_CENTRAL:
        print(f"Connected to {addr}")

        # Receive state
        alert_state = bool(int(uart.readline().decode("utf8")))

        print(f"Received alert state: {alert_state}")

    ble.stop_advertising()


def reboot():
    """Reset the board.

    Equivalent to pressing the reset button.
    """
    print("Rebooting...")

    microcontroller.reset()


def shutdown():
    """Shutdown the board.

    Will wake up when action button is pressed.
    """
    print("Shutting down...")

    # Release the BTN pin
    btn.deinit()
    alarm.exit_and_deep_sleep_until_alarms(
        alarm.pin.PinAlarm(BTN, value=False, pull=True),
    )


def print_info():
    print("\nLapsipaimen\n===========")

    serial = binascii.hexlify(microcontroller.cpu.uid).decode("utf8")
    lipo_voltage = (lipo_voltage_raw.value * 3.6) / 65536 * 2

    print(f"State: {'ALARMING' if alert_state else 'NORMAL'}")
    print(f"Silent: {silent}")
    print(f"Serial number: {serial}")
    print(f"Temperature: {microcontroller.cpu.temperature:.1f}C")
    print(f"Free RAM: {gc.mem_free()/1024:.1f}KB")  # pylint: disable=no-member
    print(f"BLE mode: {'Central' if ble_is_central else 'Peripheral'}")
    print(f"BLE address: {bytes_to_mac(ble._adapter.address.address_bytes)}")
    print(f"BLE signal strength: {ble_rssi if ble_rssi else 'N/A'}")
    print(f"BLE signal threshold: {BLE_RSSI_THRESHOLD}")
    print(f"LiPo voltage: {lipo_voltage:.2f}V")
    print(f"Powered by {os.uname().machine}\n")


print("Starting software...")
print_info()
vibrate()
blink(COLOR_CYAN)

while True:
    now = time.monotonic()
    btn_state_new = btn.value

    # Button pressed, toggle silence and show info
    if btn_state != btn_state_new and not btn_state_new:
        btn_timestamp = now
        silent = not silent

        print("Button pressed")
        print_info()

    # Button long-pressed, reboot
    if not btn_state_new and now > btn_timestamp + BTN_LONG_PRESS_SECONDS:
        print("Button long-pressed")
        blink(COLOR_PURPLE, 0.1, 5)
        shutdown()

    btn_state = btn_state_new

    # Play the next loop of alert effect if needed
    if alert_state and now > alert_timestamp + HAPTIC_EFFECT_ALERT_SECONDS:
        alert_timestamp = now

        blink(COLOR_YELLOW, 0.25)

        if not silent:
            vibrate(HAPTIC_EFFECT_ALERT, HAPTIC_EFFECT_ALERT_LEVEL)
    # Blink status led otherwise
    elif not alert_state and now > status_timestamp + LED_STATUS_SECONDS:
        status_timestamp = now

        blink(COLOR_BLUE, 0.25)

    # Try to connect or wait for connection
    if ble_is_central:
        connect()
    else:
        wait_for_connection()
