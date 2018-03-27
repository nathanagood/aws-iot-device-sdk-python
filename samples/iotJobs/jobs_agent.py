"""
"""

import argparse
import logging
import time
import json

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

logging.basicConfig()
# pylint: disable=C0103
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

logging.getLogger("AWSIoTPythonSDK").setLevel(logging.INFO)

# The MQTT topic templates for job management
NOTIFY_NEXT_TOPIC = "$aws/things/{thing}/jobs/notify-next"
NOTIFY_TOPIC = "$aws/things/{thing}/jobs/notify"
UPDATE_JOB_TOPIC = "$aws/things/{thing}/jobs/{job}/update"
UPDATE_REJECT_JOB_TOPIC = "$aws/things/{thing}/jobs/{job}/update/rejected"

# The MQTT job statuses:
JOB_SUCCEEDED = "SUCCEEDED"
JOB_IN_PROGRESS = "IN_PROGRESS"
JOB_FAILED = "FAILED"

class JobClient(object):
    """
    A handler for updating job status, executing the actual job, etc.
    """

    def __init__(self, client, thing_name, job_id, exec_handler, err_handler):
        """
        Creates the handler for the thing with the given name and the
        given job ID.
        :param client: The MQTT client to use for sending status, etc.
        :param thing_name: The name of the AWS IoT Thing
        :param job_id: The identifier of the job. 
        :param exec_handler: The function to use for handling the function.
        """
        self.__client = client
        self.__job_id = job_id
        self.__thing_name = thing_name
        self.__exec_handler = exec_handler
        self.__err_handler = err_handler
        self.__job_version = 1

        # TODO: Subscribe to the 'rejected' topics to get error
        self.__client.subscribe(
            UPDATE_REJECT_JOB_TOPIC.format(thing=thing_name,job=job_id), 
            1,
            err_handler
            )

    def __update_job_status(self, status, job_version=1, percent_complete=100):
        """
        Updates the job status to the 
        """
        status_msg = {
            'status': status,
            'statusDetails': {
                'progress': percent_complete
            },
            'expectedVersion': job_version
        }

        logger.debug('Sending job status: %s', status_msg) 

        self.__client.publish(
            UPDATE_JOB_TOPIC.format(thing=self.__thing_name),
            json.dumps(status_msg)
        )

    def __complete_job(self):
        """
        Marks the job as being complete. Just a shortcut for sending "SUCCEEDED" to 
        """
        self.__update_job_status(JOB_SUCCEEDED, self.__job_version)

    def __start_job(self):
        """
        Marks the job as being started.
        """
        pass

    def execute_job(self, job_data):
        """
        Executes the job with the given data that will be used during
        the execution of the job
        :param job_data: A dict object that contains information about the job.
        """
        self.__start_job()
        self.__exec_handler(job_data)


class JobHandler(object):

    def __init__(self, client, thing_name):
        """
        """
        self.__client = client
        self.__thing_name = thing_name

    def __select_handler(self, operation):
        if operation == 'CONTAINER_UPDATE':
            return self.execute_container_update

    def execute_container_update(self, job_data):
        """

        """
        logger.info("Starting container update...")
        

    def err_handler(self, client, userdata, message):
        """
        A function for dispatching the jobs to the correct handlers. 
        """
        logger.error("Error while processing job - %s: %s", message.topic, message.payload)


    def dispatch_jobs(self, client, userdata, message):
        """
        A function for dispatching the jobs to the correct handlers. 
        {"timestamp":1522158605,"execution":{"jobId":"20","status":"QUEUED","queuedAt":1522158605,"lastUpdatedAt":1522158605,"versionNumber":1,"executionNumber":1,"jobDocument":{"jobType":"CONTAINER_UPDATE","containerUrl":"s3://nathgood-examples/version2-container.tar"}}}
        """
        logger.debug("Dispatching job published on %s: %s", message.topic, message.payload)
        logger.debug("User data is: %s", userdata)

        job_data = json.loads(message.payload)
        job_execution_data = job_data.get('execution', None)

        if job_execution_data:
            job_id = job_execution_data.get('jobId', 0)
            job_oper = job_execution_data.get('jobDocument', {}).get('jobType', '')
            logger.debug("Now handling job %s of type %s...", job_id, job_oper)
            action_handler = self.__select_handler(job_oper)
            job_client = JobClient(self.__client, self.__thing_name, job_id, action_handler, self.err_handler)
            job_client.execute_job(job_execution_data)


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

    jobs_topic = NOTIFY_NEXT_TOPIC.format(thing=thing_name)

    logger.debug('Connecting to endpoint %s...', endpoint)
    iot_client.connect()
    handler = JobHandler(iot_client, thing_name)
    iot_client.subscribe(jobs_topic, 1, handler.dispatch_jobs)
    logger.info('Listening for jobs.')

    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info('Disconnecting...')
            iot_client.disconnect()
            break


if __name__ == "__main__":
    logger.info("Starting local jobs agent...")
    parser = argparse.ArgumentParser('jobs_agent')
    parser.add_argument('-n', '--name', required=True, help="The name of the thing connecting to AWS IoT")
    parser.add_argument('-e', '--endpoint', required=True, help="The AWS IoT endpoint")
    parser.add_argument('-k', '--key', required=True, help="The path to the private key file.")
    parser.add_argument('-c', '--certificate', required=True, help="The path to the certificate file")
    parser.add_argument('-r', '--root', required=True, help="The path to the root CA file")
    args = parser.parse_args()
    run_jobs_agent(args.name, args.endpoint, args.key, args.certificate, args.root)