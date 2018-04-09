# AWS IoT Jobs Agent Example

This example demonstrates how to use the [AWS IoT Jobs API (Application Programming Interface)](https://docs.aws.amazon.com/iot/latest/developerguide/iot-jobs.html)
to perform some local administrative tasks on a AWS Greengrass device.

# AWS Jobs API Overview

The AWS Job API is a specified set of MQTT (Message Queuing Telemetry Transport) topics and messages that allows jobs to be scheduled for remote execution in IoT devices. The API allows devices to report on the status of jobs.

The API defines a set of MQTT topics for notification of new jobs, job execution updates, and getting job updates. These topics and messages are discussed in overview here with links to the AWS IoT Jobs documentation for further information.

The API does not provide code for actually *performing* the job--this is an activity left to the implementor. Rather, the Job API is simply a structure that defines a consistent manner in which jobs may be communicated to and from IoT devices.

# Understanding the lifecycle of a job

The following sections provide an overview of how a job is created and executed using the AWS IoT Jobs API.

## Creating a new job

A job may be created either using the [AWS SDK](https://aws.amazon.com/tools/#SDKs) (Software Development Kit) or the [AWS CLI](https://aws.amazon.com/cli/) (Command Line Interface).

For an example of creating a job using the Python AWS IoT SDK (boto3), see [http://boto3.readthedocs.io/en/latest/reference/services/iot.html#IoT.Client.create_job](http://boto3.readthedocs.io/en/latest/reference/services/iot.html#IoT.Client.create_job)

To create a new job using the CLI, type a command as shown here:

    $ aws iot create-job --job-id <JOB_ID> \
    --targets <THING_ARNS> \
    --document-source <S3_DOC_LINK>

Where *JOB_ID* is the unqiue ID for the job (eg., 1, 2, or 3), THING_ARNS is a list of AWS IoT Thing ARNs ([Amazon Resource Names](https://docs.aws.amazon.com/general/latest/gr/aws-arns-and-namespaces.html#arn-syntax-iot)) in the form of `arn:aws:iot:<REGION>:<ACCOUNT NUMBER>:thing/<THING NAME>`, and <S3_DOC_LINK> is the S3 URL of the jobs document.

If the command has completed successfully, it will return with something like:

    {
        "jobArn": "arn:aws:iot:<REGION>:<ACCOUNT NUMBER>:job/<JOB ID>",
        "jobId": "<JOB ID>"
    }

If you attempt to reuse a job ID, the command will result in the error: `Job <JOB_ID> already exists.`. The jobs document is a JSON (JavaScript Object Notation) that you define and upload to
Amazon S3. The contents of the job document are used to communicate job details to your devices and the contents are used at the time you issue the command to create the job.

For example, if you want to use the jobs API to update packages on a device, you can list
the name of the package in the job document. Consider the following JSON document, which is used in
the code in this project:

    {
        "jobType": "APT_UPDATE",
        "aptPackageName": "cowsay"
    }

Be mindful of security when building this document. If you run the `job_agent.py` script on your 
device as the root user, avoid defining the jobs document in such a way that you're sending raw
commands or doing anything else that could expose your devices to increased risk. Make sure to do appropriate checking and verification in the code that --the security responsibility follows the [shared responsibility model](https://aws.amazon.com/compliance/shared-responsibility-model/) where the implementor of the code that performs the job is responsible for the security of the solution.

If the command to create the job is successful, AWS IoT will send a message to the `$aws/things/<THING NAME>/jobs/notify-next` topic (where *THING_NAME* is the name of the AWS IoT device) that looks like this:

    {
        "timestamp": 1523297701,
        "execution": {
            "jobId": "70",
            "status": "QUEUED",
            "queuedAt": 1523297701,
            "lastUpdatedAt": 1523297701,
            "versionNumber": 1,
            "executionNumber": 1,
            "jobDocument": {
                "jobType": "APT_UPDATE",
                "aptPackageName": "cowsay"
            }
        }
    }

Now that the device can get notified of the next job scheduled for execution, you can build code
that runs on the device to execute the work.

For more information about creating jobs, see "[Managing Jobs](https://docs.aws.amazon.com/iot/latest/developerguide/create-manage-jobs.html)" in the AWS documentation.

## Executing the job

To execute work, a client simply needs to subscribe to the `$aws/things/<THING NAME>/jobs/notify-next` topic (where *THING_NAME* is the name of the AWS IoT device) topic and perform an action in response to the message. During the execution, the device can send messages in a pre-defined structure to the `$aws/things/<THING NAME>/jobs/<JOB ID>/update` topic, where *THING NAME* is the name of the AWS IoT thing and *JOB ID* is the ID of the job when it was created. The update message should look like this:

    {
        "status":"SUCCEEDED",
        "statusDetails": {
            "progress":"100%"
        },
        "expectedVersion":"2"
    }

The above is an example of reporting successful completion of the job. The message is slightly different, but published to the same topic, to send an update on the job execution. See "[Report Job Execution Status](https://docs.aws.amazon.com/iot/latest/developerguide/jobs-devices.html#jobs-job-processing)" for more information.

To make subscribing to the correct topics and updating status easier, this example includes a `JobClient` that provides methods for adding filters and handlers to execute jobs. 

### Using the `JobClient` class

The `JobClient` class offers methods to simplify the interaction with the AWS IoT Jobs API. 
Two of the methods are `start()` and `add_handler()`. They are shown in here:

    job_client = JobClient(iot_client, thing_name)
    job_client.add_handler(get_job_type, 'APT_UPDATE', execute_apt_update)
    job_client.start()

The `add_handler()` method allows you to specify a filter function (here, `get_job_type`) that accepts the job document and extracts from value from it. The value is specified by `APT_UPDATE`. When the result of `get_job_type` function is `APT_UPDATE`, the `JobClient` will execute the `execute_apt_update` function. These are defined in the `jobs_agent.py` script.

The `start()` method tells the `JobClient` instance to subscribe to the `$aws/things/<THING NAME>/jobs/notify-next` topic, effectively starting executions as they appear on the topic.

An internal method to the class, `__dispatch_jobs()`, uses the filter method provided in the `add_handler()` method to choose the appropriate handling function when a message is retreived on the `$aws/things/<THING NAME>/jobs/notify-next` MQTT topic. It will update the status of the method and send an update message to the `$aws/things/<THING NAME>/jobs/<JOB ID>/update` topic when the function is complete.

See more details in comments in the `jobs_agent.py` script.

# Executing the example

To run the example script, `jobs_agent.py`, it's best if you have [virtualenv](https://virtualenv.pypa.io/en/stable/) installed and run the following commands in the
same folder as this `README.md` file:

    $ virtualenv -p python2.7 venv # Create the virtualenv 
    $ source venv/bin/activate # Set up the paths
    $ pip install -r requirements.txt # Install all Python prereqs
    $ cp settings.conf.example settings.conf

Edit the `settings.conf` file to supply the name of the thing, end hostname of the AWS IoT endpoint, and the paths to the root CA (Certificate Authority), private key, and certificate file. 

After you are finished editing the `settings.conf` file, run the example by typing the command `./start.sh`. When you see the logging message `INFO:root:Listening for jobs...`, you can create a new job using the method described under "Creating a new job".