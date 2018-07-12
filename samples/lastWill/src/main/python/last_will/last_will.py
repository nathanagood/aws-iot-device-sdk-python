'''
/*
 * Copyright 2010-2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License").
 * You may not use this file except in compliance with the License.
 * A copy of the License is located at
 *
 *  http://aws.amazon.com/apache2.0
 *
 * or in the "license" file accompanying this file. This file is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
 * express or implied. See the License for the specific language governing
 * permissions and limitations under the License.
 */
 '''

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.MQTTLib import LWT
import sys
import logging
import time
import getopt


def subscribe_callback(client, userdata, message):
    """
    A custom callback function that will be executed when a message is received on the topic.
    :param client:
    :param userdata:
    :param message:
    :return:
    """
    print("Received a new message: ")
    print(message.payload)
    print("from topic: ")
    print(message.topic)
    print("--------------\n\n")

# Usage
usage_info = """Usage:

Use certificate based mutual authentication:
python basicPubSub.py -e <endpoint> -r <rootCAFilePath> -c <certFilePath> -k <privateKeyFilePath>

Use MQTT over WebSocket:
python basicPubSub.py -e <endpoint> -r <rootCAFilePath> -w

Type "python basicPubSub.py -h" for available options.
"""
# Help info
help_info = """-e, --endpoint
    Your AWS IoT custom endpoint
-r, --rootCA
    Root CA file path
-c, --cert
    Certificate file path
-k, --key
    Private key file path
-w, --websocket
    Use MQTT over WebSocket
-h, --help
    Help information


"""

# Read in command-line parameters
use_websocket = False
host = ""
root_ca_path = ""
certificate_path = ""
private_key_path = ""
try:
    opts, args = getopt.getopt(sys.argv[1:], "hwe:k:c:r:", ["help", "endpoint=", "key=","cert=","rootCA=", "websocket"])
    if len(opts) == 0:
        raise getopt.GetoptError("No input parameters!")
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print(help_info)
            exit(0)
        if opt in ("-e", "--endpoint"):
            host = arg
        if opt in ("-r", "--rootCA"):
            root_ca_path = arg
        if opt in ("-c", "--cert"):
            certificate_path = arg
        if opt in ("-k", "--key"):
            private_key_path = arg
        if opt in ("-w", "--websocket"):
            use_websocket = True
except getopt.GetoptError:
    print(usage_info)
    exit(1)

# Missing configuration notification
missing_config = False
if not host:
    print("Missing '-e' or '--endpoint'")
    missing_config = True
if not root_ca_path:
    print("Missing '-r' or '--rootCA'")
    missing_config = True
if not use_websocket:
    if not certificate_path:
        print("Missing '-c' or '--cert'")
        missing_config = True
    if not private_key_path:
        print("Missing '-k' or '--key'")
        missing_config = True
if missing_config:
    exit(2)

# Configure logging
logger = None
if sys.version_info[0] == 3:
    logger = logging.getLogger("core")  # Python 3
else:
    logger = logging.getLogger("AWSIoTPythonSDK.core")  # Python 2
logger.setLevel(logging.DEBUG)
stream = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream.setFormatter(formatter)
logger.addHandler(stream)

# Init AWSIoTMQTTClient
iot_client = None
if use_websocket:
    iot_client = AWSIoTMQTTClient("basicPubSub", use_websocket=True)
    iot_client.configureEndpoint(host, 443)
    iot_client.configureCredentials(root_ca_path)
else:
    iot_client = AWSIoTMQTTClient("basicPubSub")
    iot_client.configureEndpoint(host, 8883)
    iot_client.configureCredentials(root_ca_path, private_key_path, certificate_path)

# AWSIoTMQTTClient connection configuration
iot_client.configureAutoReconnectBackoffTime(1, 32, 20)
iot_client.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
iot_client.configureDrainingFrequency(2)  # Draining: 2 Hz
iot_client.configureConnectDisconnectTimeout(10)  # 10 sec
iot_client.configureMQTTOperationTimeout(5)  # 5 sec

lwt_payload = ''

last_will = LWT('sdk/test/Python/lwt', lwt_payload)

# Connect and subscribe to AWS IoT
iot_client.connect(lwt=last_will)
iot_client.subscribe("sdk/test/Python", 1, subscribe_callback)
iot_client.subscribe("sdk/test/Python2", 1, subscribe_callback)
time.sleep(2)

# Publish to the same topic in a loop forever
loopCount = 0
while True:
    iot_client.publish("sdk/test/Python", "New Message " + str(loopCount), 1)
    loopCount += 1
    time.sleep(1)
