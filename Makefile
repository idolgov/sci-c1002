BOARD?=feather_nrf52840_express

FIRMWARE_VERSION?=7.0.0
FIRMWARE_FILE:=firmware-${FIRMWARE_VERSION}.uf2
FIRMWARE_REMOTE_FILE:=adafruit-circuitpython-${BOARD}-en_US-${FIRMWARE_VERSION}.uf2
FIRMWARE_URL:=https://downloads.circuitpython.org/bin/${BOARD}/en_US/${FIRMWARE_REMOTE_FILE}

BUNDLE_VERSION?=20211110
BUNDLE_DOWNLOAD_URL:=https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases/download
BUNDLE_DIR:=adafruit-circuitpython-bundle-7.x-mpy-${BUNDLE_VERSION}
BUNDLE_URL:=${BUNDLE_DOWNLOAD_URL}/${BUNDLE_VERSION}/${BUNDLE_DIR}.zip
BUNDLE_LIBS:=*/lib/adafruit_ble/* */lib/adafruit_drv2605.mpy */lib/neopixel.mpy

BOOTLOADER_PATH?=${shell findmnt -rn -S LABEL=FEATHERBOOT -o TARGET}
CIRCUITPYTHON_PATH?=${shell findmnt -rn -S LABEL=CIRCUITPY -o TARGET}

firmware:
	curl -L ${FIRMWARE_URL} > ${FIRMWARE_FILE}

libs:
	rm -rf libs
	curl -LO ${BUNDLE_URL}
	unzip -q ${BUNDLE_DIR}.zip ${BUNDLE_LIBS}
	mv ${BUNDLE_DIR}/lib libs
	rm -rf ${BUNDLE_DIR}*
	tree libs

flash:
	@if [ -z "${BOOTLOADER_PATH}" ]; then echo "Bootloader missing!" && false; fi
	rsync -avh --progress ${FIRMWARE_FILE} ${BOOTLOADER_PATH}

env:
	rm -rf env
	python3 -m venv env
	. env/bin/activate && pip3 install -r requirements.txt

lint:
	black -l 80 --check --diff *.py
	pylint -j0 -d global-statement,bare-except,protected-access *.py

install:
	@if [ -z "${CIRCUITPYTHON_PATH}" ]; then echo "Device missing!" && false; fi
	rsync -avh --progress libs/ ${CIRCUITPYTHON_PATH}/lib/
	cp code.py ${CIRCUITPYTHON_PATH}

.PHONY: firmware lib flash env lint install
