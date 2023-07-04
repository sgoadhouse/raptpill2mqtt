
# RAPTPill2MQTT - Stream the RAPT Pill Hydrometer to MQTT

Based Heavily on: https://github.com/sgoadhouse/tilt2mqtt
Which was originally from: https://github.com/LinuxChristian/tilt2mqtt

##### Table of Contents
1. [Inroduction](#intro)
2. [How to run](#howtorun)
3. [Running as a service](#runasservice)
4. [Integrate with Home Assistant](#intwithhass)
5. [Integrate with Brewers Friend](#brewers)

<a name="intro"/>

# Introduction

**Note:** This package requires a MQTT server. To get one read [here](https://philhawthorne.com/setting-up-a-local-mosquitto-server-using-docker-for-mqtt-communication/).

Wrapper for reading messages from [RAPT Pill wireless hydrometer](https://www.kegland.com.au/products/yellow-rapt-pill-hydrometer-thermometer-wifi-bluetooth/) and forwarding them to MQTT topics. 

The device acts as a simple Bluetooth Low Energy (BLE) beacon sending its data encoded within the Manufacturing Data. Details of RAPT Pill data format can be found here:
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

<a name="howtorun"/>

# How to run

If you are on Linux first install the bluetooth packages,

```bash
sudo apt-get install libbluetooth-dev
```

Then install Python dependencies

```
pip install bleson paho-mqtt requests pybluez
```

Run the script,

```
python raptpill2mqtt.py
```

**Note**: If you get a permission error try running the script as root.

The code should now listen for your RAPT Pill device and report values on the MQTT topic that matches your RAPT Pill color.

You can use the mosquitto commandline tool (on Linux) to listen for colors or the build-in MQTT client in Home Assistant,

```bash
mosquitto_sub -t 'rapt/pill/#'
```

To listen for measurements only from Orange devices run,

```bash
mosquitto_sub -t 'rapt/pill/Orange/#'
```

If your MQTT server is not running on the localhost you can set the following environmental variables,

| Varable name | Default value 
|--------------|---------------
| MQTT_IP      |     127.0.0.1
| MQTT_PORT    |          1883
| MQTT_AUTH    |          NONE
| MQTT_DEBUG   |    TRUE      

<a name="runasservice"/>

# Running raptpill2MQTT as a service on Linux

If you would like to run raptpill2MQTT as a service on Linux using systemd add this file to a systemd path (Normally /lib/systemd/system/raptpill2mqtt.service or /etc/systemd/system/raptpill2mqtt.service)

```bash
# On debian Linux add this file to /lib/systemd/system/raptpill2mqtt.service

[Unit]
Description=RAPT Pill Hydrometer Service
After=multi-user.target
Conflicts=getty@tty1.service

[Service]
Type=simple
Environment="MQTT_IP=192.168.1.2"
Environment="MQTT_AUTH={'username':\"my_username\", 'password':\"my_password\"}"
Environment="TILT_CAL_YELLOW={'sg':0.024, 'temp':0.0}"
ExecStart=/usr/bin/python3 <PATH TO YOUR FILE>/raptpill2mqtt.py
StandardInput=tty-force

[Install]
WantedBy=multi-user.target
```

Remember to update MQTT_IP, my_username, my_password, calibration constants and change the PATH variable in the script above. Then update your service,

```
sudo systemctl reload-daemon
```

OR

```
sudo systemctl --system daemon-reload
```

Will also need to enable and start the service:
```
sudo systemctl enable raptpill2mqtt
sudo systemctl start raptpill2mqtt
```

<a name="intwithhass"/>

# Using raptpill2MQTT with Home assistant

Using the MQTT sensor in home assistant you can now listen for new values and create automations rules based on the values (e.g. start a heater if the temperature is too low).

```yaml
  - platform: mqtt
    name: "RAPT Pill Orange - Temperature"
    state_topic: "rapt/pill/Orange"
    value_template: "{{ value_json.temperature_celsius_uncali | float + 0.5 | float | round(2) }}"
    unit_of_measurement: "\u2103"

  - platform: mqtt
    name: "RAPT Pill Orange - Gravity"
    state_topic: "rapt/pill/Orange"
    value_template: "{{ value_json.specific_gravity_uncali | float + 0.002 | float | round(3) }}"
```

Notice that here the calibration value is added directly to the value template in home assistant. 

![Home Assistant - Brewing](http://fredborg-braedstrup.dk/images/HomeAssistant-brewing.png)

<a name="brewers"/>

# Using with Brewers friend

Using the following [gist](https://gist.github.com/LinuxChristian/c00486eaee5a55daa790122ac4236c11) it is possible to stream the calibrated values from home assistant to the brewers friend API via a simple Python script. After this you can add the raptpill2mqtt.service to 

![Brewers Friend fermentation overview](http://fredborg-braedstrup.dk/images/BrewersFriend-fermentation.png)
