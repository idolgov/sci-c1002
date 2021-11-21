"""Lapsipaimen proto based on Adafruit Feather M0 Express.

https://github.com/idolgov/sci-c1002
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
BLE_RSSI_THRESHOLD = -78
BLE_RSSI_SAMPLES = 8
ALERT_STATE_SAMPLES = 5
LOW_BATTERY_THRESHOLD = 3.6
MEASURED_POWER = -58
ENVIRONMENTAL_FACTOR = 3
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
ble_rssis = []
ble_rssi_mean = 0
btn_state = btn.value
btn_timestamp = 0
alert_state = False
alert_states = []
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


def low_battery():
    is_low_battery = False
    lipo_voltage = (lipo_voltage_raw.value * 3.6) / 65536 * 2
    if lipo_voltage < LOW_BATTERY_THRESHOLD:
        is_low_battery = True
    return is_low_battery


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


def update_state(rssi):
    """Update the alarm state according to the new RSSI value.

    In addition to calculating mean of RSSI samples, we change
    the alarm state only if it is consistent enough.

    Return True if alert state has changed and False otherwise.
    """
    global alert_state, ble_rssi_mean

    ble_rssis.append(rssi)
    if len(ble_rssis) > BLE_RSSI_SAMPLES:
        ble_rssis.pop(0)

    ble_rssi_mean = sum(ble_rssis) / len(ble_rssis)
    new_state = ble_rssi_mean < BLE_RSSI_THRESHOLD

    alert_states.append(new_state)
    if len(alert_states) > ALERT_STATE_SAMPLES:
        alert_states.pop(0)

    # Not enough measurements yet, abort
    if (
        len(ble_rssis) < BLE_RSSI_SAMPLES
        or len(alert_states) + 1 < ALERT_STATE_SAMPLES
    ):
        return False

    # We've measured enough consecutive states
    if all(alert_states) or not any(alert_states):
        # Current state has changed
        if alert_state != new_state:
            alert_state = new_state

            return True

    return False


def connect():
    """Try to connect to a peripheral device.

    We only connect to a device when it is too far away or has just
    returned into allowed radius in order to trigger or dismiss an
    alert.
    """
    global ble_rssis

    connection = None

    # print("Scanning...")

    for adv in ble.start_scan(
        ProvideServicesAdvertisement, timeout=1, minimum_rssi=-100
    ):
        # Check that we are connecting to the right device
        addr = bytes_to_mac(adv.address.address_bytes)
        if addr != BLE_MAC_PERIPHERAL:
            continue

        # Check if we can communicate with the device
        if not hasattr(adv, "services") or not UARTService in adv.services:
            continue

        # Abort scaning if state has not changed
        if not update_state(adv.rssi):
            break

        try:
            print(f"Connecting to {addr}...")

            connection = ble.connect(adv)

            print("Connected!")
            break
        except:
            print("Connection failed!")
            continue
    else:
        print("No devices found!")
        update_state(BLE_RSSI_THRESHOLD - 1)

    ble.stop_scan()

    if not connection:
        return

    print_info()

    # Send own MAC address and alert state
    try:
        uart = connection[UARTService]  # pylint: disable=redefined-outer-name
        uart.write(ble._adapter.address.address_bytes)
        time.sleep(0.2)
        print(f"Sending alert state: {alert_state}")
        uart.write(str(int(alert_state)).encode("utf-8"))
    except:
        print("Connection failed!")
        ble_rssis = []
    finally:
        connection.disconnect()


def wait_for_connection():
    """Wait for a connection from a central device."""
    global alert_state

    if not ble._adapter.advertising:
        print("Connecting...")

        ble.start_advertising(advertisement=advertisement, scan_response=None)

    if not ble.connected:
        time.sleep(0.2)
        return

    # Receive MAC address of the central
    addr = bytes_to_mac(uart.read(6))

    if addr == BLE_MAC_CENTRAL:
        print(f"Connected to {addr}")

        data = uart.readline().decode("utf8").strip()

        if data:
            # Receive state
            alert_state = bool(int(data))

            print(f"Received alert state: {alert_state}")

    # ble.stop_advertising()


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
        alarm.pin.PinAlarm(pin=BTN, value=False, pull=True),
    )


def distance():
    dist = None

    if ble_rssi_mean:
        dist = 10 ** (
            (MEASURED_POWER - ble_rssi_mean) / (10 * ENVIRONMENTAL_FACTOR)
        )

    return f"{dist:.2f}m" if dist else "N/A"


def print_info():
    print("\nLapsipaimen\n===========")

    serial = binascii.hexlify(microcontroller.cpu.uid).decode("utf8")
    lipo_voltage = (lipo_voltage_raw.value * 3.6) / 65536 * 2

    print(f"State: {'ALARMING' if alert_state else 'NORMAL'}")
    print(f"Measured alert states: {alert_states}")
    print(f"Mute: {silent}")
    print(f"BLE mode: {'Central' if ble_is_central else 'Peripheral'}")
    print(f"BLE address: {bytes_to_mac(ble._adapter.address.address_bytes)}")
    print(f"BLE TX power: {ble.tx_power}dBm")
    print(f"BLE RSSI samples: {ble_rssis if ble_rssis else 'N/A'}")
    print(f"BLE RSSI mean: {ble_rssi_mean if ble_rssi_mean else 'N/A'}")
    print(f"BLE RSSI threshold: {BLE_RSSI_THRESHOLD}")
    print(f"Approximate distance: {distance()}")
    print(f"Temperature: {microcontroller.cpu.temperature:.1f}C")
    print(f"Free RAM: {gc.mem_free()/1024:.1f}KB")  # pylint: disable=no-member
    print(f"LiPo voltage: {lipo_voltage:.2f}V")
    print(f"Serial number: {serial}")
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

        if low_battery():
            blink(COLOR_RED, 0.25)
        else:
            blink(COLOR_BLUE, 0.25)

    # Try to connect or wait for connection
    if ble_is_central:
        connect()
    else:
        wait_for_connection()
