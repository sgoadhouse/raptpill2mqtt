#!/usr/bin/env python3
"""Wrapper for reading messages from RAPT Pill wireless hydrometer and forwarding them to MQTT topics. 

The device is a iBluetooth Low Energy (BLE) device that sends out a
set of 6 advertisements for every interval as set in the Pill.

Details of data format can be found here:
https://gitlab.com/rapt.io/public/-/wikis/Pill-Hydrometer-Bluetooth-Transmissions

The raw values read from the RAPT Pill are (possibly) uncalibrated and should be calibrated before use. The script works a follows,

 1. Listen for local BLE devices
 2. If found the callback is triggered
  * Use Manufacturer ID "5241" (0x4152) to determine that it is from a RAPT Pill (cannot yet distinguish multiple Pills)
  * Extract and convert measurements from the device
  * Construct a JSON payload
  * Send payload to the MQTT server
 3. Stop listening and sleep for X minutes before getting a new measurement

This script has been tested on Linux.

# How to run

First install Python dependencies

 pip install beacontools paho-mqtt requests pybluez

Run the script,

 python raptpill2mqtt.py

Note: A MQTT server is required.

"""

from time import sleep
from struct import unpack
from bleson import get_provider, Observer
from bleson.logger import DEBUG, ERROR, WARNING, INFO, set_level
from datetime import datetime

import logging as lg
import os
import json
import paho.mqtt.publish as publish
import requests
from ast import literal_eval

#
# Constants
#
#@@@#sleep_interval = 60.0*10  # How often to listen for new messages in seconds
sleep_interval = 60.0*5  # How often to listen for new messages in seconds

lg.basicConfig(level=lg.INFO)
LOG = lg.getLogger()

# Create handlers
c_handler = lg.StreamHandler()
f_handler = lg.FileHandler('/tmp/rapt-pill.log')
c_handler.setLevel(lg.DEBUG)
f_handler.setLevel(lg.INFO)

# Create formatters and add it to handlers
c_format = lg.Formatter('%(name)s - %(levelname)s - %(message)s')
f_format = lg.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Add handlers to the logger
LOG.addHandler(c_handler)
LOG.addHandler(f_handler)

# Unique bluetooth IDs for Tilt sensors
TILTS = {
        'a495bb10-c5b1-4b44-b512-1370f02d74de': 'Red',
        'a495bb20-c5b1-4b44-b512-1370f02d74de': 'Green',
        'a495bb30-c5b1-4b44-b512-1370f02d74de': 'Black',
        'a495bb40-c5b1-4b44-b512-1370f02d74de': 'Purple',
        'a495bb50-c5b1-4b44-b512-1370f02d74de': 'Orange',
        'a495bb60-c5b1-4b44-b512-1370f02d74de': 'Blue',
        'a495bb70-c5b1-4b44-b512-1370f02d74de': 'Yellow',
        'a495bb80-c5b1-4b44-b512-1370f02d74de': 'Pink',
        '020001c0-1cf3-4090-d644-781eff3a2cfe': 'RAPT Yellow',
}

calibration = {
        'Red'    : literal_eval(os.getenv('TILT_CAL_RED', "None")),
        'Green'  : literal_eval(os.getenv('TILT_CAL_GREEN', "None")),
        'Black'  : literal_eval(os.getenv('TILT_CAL_BLACK', "None")),
        'Purple' : literal_eval(os.getenv('TILT_CAL_PURPLE', "None")),
        'Orange' : literal_eval(os.getenv('TILT_CAL_ORANGE', "None")),
        'Blue'   : literal_eval(os.getenv('TILT_CAL_BLUE', "None")),
        'Yellow' : literal_eval(os.getenv('TILT_CAL_YELLOW', "None")),
        'Pink'   : literal_eval(os.getenv('TILT_CAL_PINK', "None")),
        'RAPT Yellow' : literal_eval(os.getenv('TILT_CAL_YELLOW', "None")),
        'unknown': literal_eval(os.getenv('TILT_UNKNOWN', "None")),
}
#@@@#LOG.info("TILT Blue Calibration: {}".format(calibration['Blue']))


# MQTT Settings
config = {
        'host': os.getenv('MQTT_IP', '127.0.0.1'),
        'port':int(os.getenv('MQTT_PORT', 1883)),
        'auth': literal_eval(os.getenv('MQTT_AUTH', "None")),
        'debug': os.getenv('MQTT_DEBUG', True),
}
#@@@#LOG.info("MQTT Broker: {}:{}  AUTH:{}".format(config['host'], config['port'], config['auth']))
#@@@#LOG.info("AUTH['username']:{}  AUTH['password']:{}".format(config['auth']['username'],config['auth']['password']))

def on_advertisement(advertisement):
    """Message recieved from RAPT Pill
    """

    msgs = []
    color = "unknown"

    if advertisement.mfg_data is not None:
        rssi = advertisement.rssi
        uuid128 = advertisement.uuid128s
        address = advertisement.address
        payload = advertisement.mfg_data.hex()
        mfg_id = payload[0:4]
        if mfg_id == "4b45" and payload[4:6] == "47":
            # it is a RAPT Pill, but the firmware version annoucement
            firmware_version =  advertisement.mfg_data[3:]
            LOG.info("Pill Firmware: {}".format(firmware_version))
        elif mfg_id == "5241":
            # OK, it is a RAPT Pill message with data
            LOG.info(advertisement)
            msg_type = payload[4:10]
            
            if (msg_type == "505401"):
                # V1 Format Data
                LOG.info('Unable to decode V1 format data: ', payload)
            elif (msg_type == "505464"):
                # Device Type String
                device_type = advertisement.mfg_data[5:]
                LOG.info('Device Type: ({}) {}'.format(device_type.hex(), device_type.decode("utf-8")))
            elif (msg_type == "505402"):
                try:
                    # V2 Format Data - get the uncalibrated values
                    data = unpack(">BBfHfhhhH",advertisement.mfg_data[5:])
                    # Pad (specified to always be 0x00)
                    pad = data[0]
                    # If 0, gravity velocity is invalid, if 1, it is valid
                    gravity_velocity_valid = data[1]
                    # floating point, points per day, if gravity_velocity_valid is 1
                    gravity_velocity = data[2]
                    # temperature in Kelvin, multiplied by 128
                    temperatureC = (data[3] / 128) - 273.15
                    temperatureF = (temperatureC * 9/5) + 32
                    # specific gravity, floating point, apparently in points
                    specific_gravity = data[4] / 1000
                    # raw accelerometer dta * 16, signed
                    accel_x = data[5] / 16
                    accel_y = data[6] / 16
                    accel_z = data[7] / 16
                    # battery percentage * 256, unsigned
                    battery = data[8] / 256

                    # See if have calibration values. If so, use them.
                    if (calibration[color]):
                        suffix = "cali"
                        temperatureF += calibration[color]['temp']
                        specific_gravity += calibration[color]['sg']
                    else:
                        suffix = "uncali"
                    
                    if (pad != 0):
                        LOG.error("INVALID FORMAT for RAPT Pill Data:", advertisement.mfg_data)
                    else:
                        if gravity_velocity_valid == 1:
                            LOG.info("Pill: {}  Gravity: {:.4f} (Pts/Day: {:.1f}) Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {}".format(address.address, specific_gravity, gravity_velocity, temperatureC, temperatureF, battery, rssi))
                            mqttdata = {
                                "specific_gravity_"+suffix: "{:.4f}".format(specific_gravity),
                                "specific_gravity_pts_per_day_"+suffix: "{:.1f}".format(gravity_velocity),
                                "temperature_celsius_"+suffix: "{:.2f}".format(temperatureC),
                                "temperature_farenheit_"+suffix: "{:.1f}".format(temperatureF),
                                "battery": "{:.1f}".format(battery),
                                "rssi": "{:d}".format(rssi),
                                "time": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                            }

                        else:
                            LOG.info("Pill: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {}".format(address.address, specific_gravity, temperatureC, temperatureF, battery, rssi))
                            mqttdata = {
                                "specific_gravity_"+suffix: "{:.4f}".format(specific_gravity),
                                "temperature_celsius_"+suffix: "{:.2f}".format(temperatureC),
                                "temperature_farenheit_"+suffix: "{:.1f}".format(temperatureF),
                                "battery": "{:.1f}".format(battery),
                                "rssi": "{:d}".format(rssi),
                                "time": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                            }

                        # Create message                                        QoS   Retain message
                        msgs.append(("rapt-pill/{}".format(color), json.dumps(mqttdata), 2,    1))

                        # Send message via MQTT server
                        publish.multiple(msgs, hostname=config['host'], port=config['port'], auth=config['auth'], protocol=4)
                except KeyError:
                    LOG.error("Device does not look like a RAPT Pill Hydrometer.")


def scan(scantime=25.0):        
    LOG.info("Create BLE Scanner")
    adapter = get_provider().get_adapter()

    observer = Observer(adapter)
    observer.on_advertising_data = on_advertisement
 
    LOG.info("Started scanning")
    # Start scanning
    observer.start()
   
    # Time to wait for RAPT Pill to respond
    sleep(scantime)

    # Stop again
    observer.stop()
    LOG.info("Stopped scanning")
   

# Set Log level for bleson scanner to ERROR to prevent the large number of WARNINGs from going into the log
set_level(ERROR)
        
while(1):

    # Scan for iBeacons of RAPT Pill for 75 seconds
    scan(75.0)

    #@@@## Test mqtt publish with sample data
    #@@@#callback("ea:ca:eb:f0:0f:b5", -95, "", {'uuid': 'a495bb60-c5b1-4b44-b512-1370f02d74de', 'major': 73, 'minor': 989})
    #@@@#sleep(2.0)

    # Wait until next scan period
    sleep(sleep_interval)
