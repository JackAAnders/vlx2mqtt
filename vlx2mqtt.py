#!/usr/bin/env python3
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys
import signal
import logging
import argparse
import asyncio
import time
from configparser import ConfigParser
from configparser import ExtendedInterpolation
import paho.mqtt.client as mqtt

from pyvlx import Position, PyVLX, OpeningDevice
from pyvlx.log import PYVLXLOG

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='''glues between pyvlx and mqtt stuff'''
)
parser.add_argument(
    'config_file',
    metavar="<config_file>",
    help="file with configuration"
)
args = parser.parse_args()


# read and parse config file
config = ConfigParser(interpolation=ExtendedInterpolation())
config.read(args.config_file)
# [mqtt]
MQTT_HOST = config.get("mqtt", "host")
MQTT_PORT = config.getint("mqtt", "port")
MQTT_USER = config.get("mqtt", "login")
MQTT_PW = config.get("mqtt", "password")
ROOTTOPIC = config.get("mqtt", "roottopic")
STATUSTOPIC = config.get("mqtt", "statustopic")
# [velux]
VLX_HOST = config.get("velux", "host")
VLX_PW = config.get("velux", "password")
# [log]
LOGFILE = config.get("log", "logfile")
VERBOSE = config.get("log", "verbose")

APPNAME = "vlx2mqtt"

RUNNING = True
MQTT_CONN = False
nodes = {}

# init logging
LOGFORMAT = '%(asctime)-15s %(message)s'
if VERBOSE:
    logging.basicConfig(
        stream=sys.stdout,
        # ilename=LOGFILE,
        format=LOGFORMAT,
        level=logging.DEBUG
    )
else:
    logging.basicConfig(
        stream=sys.stdout,
        # filename=LOGFILE,
        format=LOGFORMAT,
        level=logging.INFO
    )

logging.info("Starting %s", APPNAME)
if VERBOSE:
    logging.info("DEBUG MODE")
else:
    logging.debug("INFO MODE")

PYVLXLOG.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
PYVLXLOG.addHandler(ch)

# MQTT
MQTT_CLIENT_ID = APPNAME + "_%d" % os.getpid()
MQTTC = mqtt.Client(MQTT_CLIENT_ID)
# if (MQTT_USER is not None and MQTT_PW is not None):
MQTTC.username_pw_set(MQTT_USER, MQTT_PW)


def mqtt_on_connect(client, userdata, flags, return_code):
    '''
        @return_code
        0: Connection successful
        1: Connection refused - incorrect protocol version
        2: Connection refused - invalid client identifier
        3: Connection refused - server unavailable
        4: Connection refused - bad username or password
        5: Connection refused - not authorised
        6-255: Currently unused.
    '''
    _ = (client, userdata, flags)  # pylint: disable=unused-argument

    global MQTT_CONN  # pylint: disable=global-statement
    logging.debug("mqtt_on_connect return_code: %s", str(return_code))
    if return_code == 0:
        logging.info("Connected to %s:%s", MQTT_HOST, MQTT_PORT)
        MQTTC.publish(STATUSTOPIC, "CONNECTED", retain=True)

        # register devices
        for node in pyvlx.nodes:
            if isinstance(node, OpeningDevice):
                logging.debug("Subscribing to %s/%s/set", ROOTTOPIC, node.name)
                MQTTC.subscribe(ROOTTOPIC + '/' + node.name + '/set')
        MQTT_CONN = True
    elif return_code == 1:
        logging.info("Connection refused - unacceptable protocol version")
        cleanup()
    elif return_code == 2:
        logging.info("Connection refused - identifier rejected")
        cleanup()
    elif return_code == 3:
        logging.info("Connection refused - server unavailable")
        logging.info("Retrying in 10 seconds")
        time.sleep(10)
    elif return_code == 4:
        logging.info("Connection refused - bad user name or password")
        cleanup()
    elif return_code == 5:
        logging.info("Connection refused - not authorised")
        cleanup()
    else:
        logging.warning("Something went wrong. RC: %s", str(return_code))
        cleanup()


def mqtt_on_disconnect(mosq, obj, return_code):
    """ on disconnect """
    _ = (mosq, obj)  # pylint: disable=unused-argument
    global MQTT_CONN  # pylint: disable=global-statement
    MQTT_CONN = False
    if return_code == 0:
        logging.info("Clean disconnection")
    else:
        logging.info("Unexpected disconnection. Reconnecting in 5 seconds")
        logging.debug("return_code: %s", return_code)
        time.sleep(5)


def mqtt_on_message(client, userdata, msg):
    """ on message """
    _ = (client, userdata)  # pylint: disable=unused-argument

    # set OpeningDevice?
    for node in pyvlx.nodes:
        if node.name+'/set' not in msg.topic:
            continue
        logging.debug("Setting %s to %d%%", node.name, int(msg.payload))
        nodes[node.name] = int(msg.payload)


def cleanup(signum=signal.SIGTERM, frame=None):
    """ cleanup """
    _ = (frame)  # pylint: disable=unused-argument
    global RUNNING  # pylint: disable=global-statement
    RUNNING = False
    logging.info("Exiting on signal %d", signum)


# note: only subclasses of OpeningDevice get registered
async def vlx_cb(node):
    """ vlx call back function """
    global MQTT_CONN  # pylint: disable=global-statement,global-variable-not-assigned
    if not MQTT_CONN:
        return
    logging.debug("%s at %d%%", node.name, node.position.position_percent)
    MQTTC.publish(
        ROOTTOPIC + '/' + node.name,
        node.position.position_percent,
        retain=False
    )


async def main(loop):
    """ async main loop """
    global RUNNING  # pylint: disable=global-statement,global-variable-not-assigned
    global pyvlx, MQTTC  # pylint: disable=global-statement
    logging.debug("klf200      : %s", VLX_HOST)
    logging.debug("MQTT broker : %s", MQTT_HOST)
    logging.debug("  port      : %s", str(MQTT_PORT))
    logging.debug("statustopic : %s", str(STATUSTOPIC))

    # Connect to the broker and enter the main loop
    result = MQTTC.connect(MQTT_HOST, MQTT_PORT, 60)
    while result != 0:
        logging.info("Connection failed with error code %s. Retrying", result)
        await asyncio.sleep(10)
        result = MQTTC.connect(MQTT_HOST, MQTT_PORT, 60)
    MQTTC.publish(STATUSTOPIC, "STARTED", retain=True)

    # seems as it must be prior to MQTTC loop.
    # Otherwise mqtt will not receiving anything...
    pyvlx = PyVLX(host=VLX_HOST, password=VLX_PW, loop=loop)
    await pyvlx.load_nodes()

    # Define callbacks
    MQTTC.on_connect = mqtt_on_connect
    MQTTC.on_message = mqtt_on_message
    MQTTC.on_disconnect = mqtt_on_disconnect

    MQTTC.loop_start()
    await asyncio.sleep(2)

    MQTTC.publish(STATUSTOPIC, "KLF200_available", retain=True)

    logging.debug("vlx nodes   : %s", len(pyvlx.nodes))
    for node in pyvlx.nodes:
        logging.debug("  %s", node.name)

    # register callbacks
    for node in pyvlx.nodes:
        if isinstance(node, OpeningDevice):
            node.register_device_updated_cb(vlx_cb)
            logging.debug("watching: %s", node.name)
        else:
            logging.debug("   Other node type: %s", type(node))

    while RUNNING:
        await asyncio.sleep(1)

        # see if we received some mqtt commands
        for name, value in list(nodes.items()):
            if value >= 0:
                nodes[name] = -1  # mark execuded
                await pyvlx.nodes[name].set_position(
                    Position(position_percent=value)
                )

    logging.info("Disconnecting from KLF")
    MQTTC.publish(STATUSTOPIC, "DISCONNECTING KLF", retain=True)
    await pyvlx.disconnect()
    MQTTC.publish(STATUSTOPIC, "DISCONNECTED KLF", retain=True)

    logging.info("Disconnecting from broker")
    # Publish a retained message to state that this client is offline
    MQTTC.publish(STATUSTOPIC, "DISCONNECTED", retain=True)
    MQTTC.disconnect()
    MQTTC.loop_stop()

# Use the signal module to handle signals
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


if __name__ == '__main__':
    # pylint: disable=invalid-name
    if sys.version_info.major == 3 and sys.version_info.minor < 10:
        # less than 3.10.0
        io_loop = asyncio.get_event_loop()
    else:
        # equal or greater than 3.10.0
        try:
            io_loop = asyncio.get_running_loop()
        except RuntimeError:
            io_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(io_loop)

    try:
        io_loop.run_until_complete(main(io_loop))
    except KeyboardInterrupt:
        logging.info("Interrupted by keypress")

    io_loop.close()
    sys.exit(0)
