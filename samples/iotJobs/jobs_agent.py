"""
Provides a demonstration of how an Python program could handle AWS IoT Jobs.
See the `README.md` for more information about how this example works.
"""

import argparse
import json
import logging
import os
import platform
import time
import uuid
from subprocess import call

import boto3
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

logging.basicConfig()
# pylint: disable=C0103
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

logging.getLogger("AWSIoTPythonSDK").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("s3transfer").setLevel(logging.WARNING)

# The MQTT topic templates for job management
NOTIFY_NEXT_TOPIC = "$aws/things/{thing}/jobs/notify-next"
NOTIFY_TOPIC = "$aws/things/{thing}/jobs/notify"
UPDATE_JOB_TOPIC = "$aws/things/{thing}/jobs/{job}/update"
UPDATE_REJECT_JOB_TOPIC = "$aws/things/{thing}/jobs/{job}/update/rejected"

# The MQTT job statuses:
JOB_SUCCEEDED = "SUCCEEDED"
JOB_IN_PROGRESS = "IN_PROGRESS"
JOB_FAILED = "FAILED"

# Defaults
DEFAULT_MQTT_QOS = 1


class JobException(Exception):
    """
    An exception the occurs in the JobClient
    """
    pass


class JobClient(object):
    """
    A class for handling jobs. It contains a few convinience methods for adding
    handlers to handle different job documents.
    """

    def __init__(self, client, thing_name):
        """
        Initializes the class with the provided AWS IoT client and thing name.

        :param client: The `AWSIoTMQTTClient` used to connect to AWS IoT
        :param thing_name: The name of the AWS IoT thing. This will be used to
                construct the jobs MQTT topics.
        """
        self.__client = client
        self.__thing_name = thing_name
        self.__handlers = []

    def __update_job_status(self, status, job_version=1, percent_complete=100):
        """
        Updates the job status to the status that is passed in.

        :param status: the status (`SUCCEEDED`, `FAILED`, etc.) of the job.
        :param job_version: the version of the job's data.
        :param percent_complete: the percent that the job is complete.
        """
        status_msg = {
            'status': status,
            'statusDetails': {
                'progress': percent_complete
            },
            'expectedVersion': job_version
        }

        logger.debug('Sending job status: %s', status_msg)

        self.__client.publishAsync(
            UPDATE_JOB_TOPIC.format(thing=self.__thing_name),
            json.dumps(status_msg)
        )

    def __complete_job(self):
        """
        Marks the job as being complete. Just a shortcut for sending "SUCCEEDED" as the status
        """
        self.__update_job_status(JOB_SUCCEEDED)

    def __start_job(self):
        """
        Marks the job as being started.
        """
        pass

    def __log_noop(self, job_document):
        """
        Logs a warning to let the caller know that nothing handles the particular
        document.
        """
        # TODO: Put in option for throwing an error and raise the error if the
        # option is set.
        logger.warning('No handler defined for document: %s', job_document)

    def __select_handler(self, job_document):
        """
        Iterates through the registered handlers and chooses the first one that
        matches based on the provided filter and expression.
        """
        for handler_def in self.__handlers:
            if handler_def['expr'](job_document) == handler_def['val']:
                return handler_def['handler']

        return self.__log_noop

    def __build_status_message(self, status, percent_complete, job_version=1):
        status_msg = {
            'status': status,
            'statusDetails': {
                'progress': "{}%".format(percent_complete)
            },
            'expectedVersion': job_version
        }
        return status_msg

    def __err_handler(self, job_id, err):
        """
        Handles the error by notifying the AWS IoT job API that something went wrong with the
        job.
        """
        logger.error('Error while processing job with ID %s: %s',
                     job_id,
                     err.message
                    )
    #pylint: disable=unused-argument
    def __dispatch_jobs(self, client, userdata, message):
        """
        A function for dispatching the jobs to the correct handlers.

            {
                "timestamp": 1522158605,
                "execution": {
                    "jobId": "20",
                    "status": "QUEUED",
                    "queuedAt": 1522158605,
                    "lastUpdatedAt": 1522158605,
                    "versionNumber": 1,
                    "executionNumber": 1,
                    "jobDocument": {
                        "jobType": "CONTAINER_UPDATE",
                        "containerUrl": "s3://nathgood-examples/version2-container.tar"
                    }
                }
            }

        """

        logger.debug("Dispatching job published on %s: %s",
                     message.topic, message.payload)
        logger.debug("User data is: %s", userdata)

        job_data = json.loads(message.payload)
        job_execution_data = job_data.get('execution', None)

        if job_execution_data:
            job_id = job_execution_data.get('jobId', 0)
            job_document = job_execution_data.get('jobDocument', {})
            logger.debug("Now handling job %s with document %s...",
                         job_id, job_document)
            action_handler = self.__select_handler(job_document)

            status = self.__build_status_message(JOB_IN_PROGRESS, 50)

            self.__client.publishAsync(
                UPDATE_JOB_TOPIC.format(
                    thing=self.__thing_name,
                    job=job_id
                ),
                json.dumps(status),
                DEFAULT_MQTT_QOS
            )

            try:
                is_successful = action_handler(
                    job_execution_data.get('jobDocument', {}))
                if not is_successful:
                    raise JobException(
                        'Job failed. Check logs for more information.')
            except JobException as job_err:
                self.__err_handler(job_id, job_err)

            complete_status = self.__build_status_message(
                JOB_SUCCEEDED, 100, 2)

            self.__client.publishAsync(
                UPDATE_JOB_TOPIC.format(
                    thing=self.__thing_name,
                    job=job_id
                ),
                json.dumps(complete_status),
                DEFAULT_MQTT_QOS
            )

    def start(self):
        """
        Starts the jobs client by listening to the jobs topic and dispatching work to the
        handlers.
        """
        self.__client.subscribeAsync(NOTIFY_NEXT_TOPIC.format(thing=self.__thing_name),
                                     1,
                                     messageCallback=self.__dispatch_jobs
                                    )
        logger.info("Listening for jobs...")

    def add_handler(self, expr, val, handler):
        """
        Adds, or registers, the given handler with the expression and value. The __select_handler
        method will use the expr and val values to select the first matching handler during
        dispatching the work.
        :param expr: The expression for choosing a value from the jobs document
        :param val: The value that--when true--signifies the handler is correct for handling the
            job document
        :param handler: The function for handling the job.
        """
        logger.debug('Adding job handler...')
        self.__handlers.append({
            'expr': expr,
            'val': val,
            'handler': handler
        })


def __parse_s3_url(s3_uri):
    """
    Parses the S3 URI and returns a tuple with the bucket name and the key
    """
    # TODO: this may be a little fragile; replace with regex?
    s3_parts = s3_uri.split('/')
    return (s3_parts[2], '/'.join(s3_parts[3:]))


def get_job_type(job_document):
    """
    Returns the "job type" from the job document that, in this case, will tell us how
    to handle the job.
    :param job_document: The content of the jobDocument element from the job message.
    """
    return job_document.get('jobType', '')


def execute_apt_update(job_data):
    """
    Executes an example "apt" update on operating systems that use apt.
    """
    my_os = platform.platform()

    supported_apt_platforms = [
        'Debian',
        'Ubuntu'
    ]

    for supported_os in supported_apt_platforms:
        if supported_os in my_os:
            # The OS supports apt, so put together the command and use it to
            # install a package...
            pkg_name = job_data.get('aptPackageName', None)
            if pkg_name:
                apt_cmd = 'apt-get install {}'.format(pkg_name)
                exit_code = call(apt_cmd, shell=True)
                if exit_code:
                    return True
                else:
                    raise JobException(
                        'Error while attempting to install package {}'.format(pkg_name))
            else:
                raise JobException('Could not find \'aptPackageName\'')

    logger.warning("Cannot install package on current platform!")
    return False


def execute_container_update(job_data):
    """
    Executes an example Docker container update.
    """
    logger.info("Starting container update...")
    download_dir = os.environ.get('TMP_DIR', '/tmp')
    download_file = '{}.tar'.format(uuid.uuid4())
    download_path = os.path.join(download_dir, download_file)

    bucket_name, key_name = __parse_s3_url(job_data.get('containerUrl'))

    logger.debug("Downloading content from bucket %s to local file %s...",
                 bucket_name,
                 download_path
                )

    s3 = boto3.resource('s3')
    s3.Bucket(bucket_name).download_file(key_name, download_path)

    # TODO: Update container code here...

    logger.info("Finished container update.")

    return True


def run_jobs_agent(thing_name, endpoint, private_key, certificate_file, root_ca):
    """
    Creates the IoT client and subscribes to the jobs MQTT topics with
    handlers to handle the jobs
    """
    logger.debug('Using thing name: %s', thing_name)

    iot_client = AWSIoTMQTTClient(thing_name)
    iot_client.configureEndpoint(endpoint, 8883)
    iot_client.configureCredentials(root_ca, private_key, certificate_file)
    iot_client.configureConnectDisconnectTimeout(10)
    iot_client.configureAutoReconnectBackoffTime(1, 32, 20)
    iot_client.configureOfflinePublishQueueing(-1)
    iot_client.configureDrainingFrequency(2)
    iot_client.configureMQTTOperationTimeout(5)

    logger.debug('Connecting to endpoint %s...', endpoint)
    iot_client.connect()
    job_client = JobClient(iot_client, thing_name)
    job_client.add_handler(
        get_job_type, 'CONTAINER_UPDATE', execute_container_update)
    job_client.add_handler(get_job_type, 'APT_UPDATE', execute_apt_update)
    job_client.start()
    time.sleep(2)

    while True:
        try:
            time.sleep(.5)
        except KeyboardInterrupt:
            logger.info('Disconnecting...')
            iot_client.disconnect()
            break


if __name__ == "__main__":
    logger.info("Starting local jobs agent...")
    parser = argparse.ArgumentParser('jobs_agent')
    parser.add_argument('-n', '--name', required=True,
                        help="The name of the thing connecting to AWS IoT")
    parser.add_argument('-e', '--endpoint', required=True,
                        help="The AWS IoT endpoint")
    parser.add_argument('-k', '--key', required=True,
                        help="The path to the private key file.")
    parser.add_argument('-c', '--certificate', required=True,
                        help="The path to the certificate file")
    parser.add_argument('-r', '--root', required=True,
                        help="The path to the root CA file")
    args = parser.parse_args()
    run_jobs_agent(args.name, args.endpoint, args.key,
                   args.certificate, args.root)
