
"""
/*
* Copyright 2010-2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
"""
from __future__ import print_function

import argparse
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

# pylint: disable=C0103
logger = logging.getLogger()
# pylint: enable=C0103
logger.setLevel(logging.DEBUG)

# Note: This is an overly-permissive policy and should not be used in a
# production scenario. Make sure to more narrowly-define permissions here,
# even for a default policy.
# Optionally, use the --policy-name parameter to specify an existing
# policy
DEFAULT_IOT_POLICY = """
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "iot:Publish",
                "iot:Subscribe",
                "iot:Connect",
                "iot:Receive"
            ],
            "Resource": [
                "*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "greengrass:*"
            ],
            "Resource": [
                "*"
            ]
        }
    ]
}
""".strip()


def __parse_device_def_arn(device_definition_arn):
    """
    Parses the ARN and returns a tuple that includes the device definition ID and the
    device definition version ID.

    :param device_definition_arn: The ARN of the device definition version.
    """
    # arn:aws:greengrass:<region>:<account>:/greengrass/definition/devices\
    # /<id>/versions/<version id>
    # Note: this function could use something like a regex to valid the correct
    # formatting. However, in the case Amazon Resource Names (ARNs) have a defined
    # format and we are getting the ARN from the an AWS response so we should be
    # able to assume the ARN is formatted correctly.
    arn_parts = device_definition_arn.split(':')
    uri_parts = arn_parts[5].split('/')
    return (uri_parts[4], uri_parts[6])


def get_thing_details(thing_name):
    """
    Returns details about a thing, if the thing is found. If it's not found
    it will return None.

    :param thing_name: str Name of the AWS IoT thing to find.
    """
    result = None
    iot_client = boto3.client('iot')
    try:
        thing_description = iot_client.describe_thing(
            thingName=thing_name
        )
        result = {
            'name': thing_description['thingName'],
            'arn': thing_description['thingArn']
        }

        # Get the principals (certificates) associated with the thing.
        # The certificate ARN, along with the thing ARN, are required
        # in the AWS Greengrass group definition.
        principals = iot_client.list_thing_principals(
            thingName=thing_name
        )

        result['certificateArn'] = next(
            iter(principals['principals'] or []), None)

    except ClientError:
        logger.warning("Did not find thing with name '%s'", thing_name)

    return result


def provision_thing(thing_name, private_key_path, public_key_path, certificate_path,
                    policy_name=None):
    """
    Provisions a new IoT thing with the provided name and saves the keys and
    certificates in the path provided.
    
    :param thing_name: str Name of the IoT thing to add
    :param private_key_path: The full file name in which to save the private key.
    :param public_key_path: The full file name in which to save the public key.
    :param certificate_path: The full file name in which to save the certificate.
    :param policy_name: (optional, str) Name of an existing IoT policy to use.
    """
    logger.info('Provisioning AWS IoT thing %s...', thing_name)
    result = None
    try:
        iot_client = boto3.client('iot')
        new_thing = iot_client.create_thing(
            thingName=thing_name
        )
        logger.debug('Created new thing %s', new_thing['thingName'])

        result = {
            'name': new_thing['thingName'],
            'arn': new_thing['thingArn']
        }

        # Provision keys and certificates for the AWS IoT thing
        # since it's newly-created.
        keys_and_cert = iot_client.create_keys_and_certificate(
            setAsActive=True
        )

        with open(private_key_path, 'w+') as private_key:
            private_key.write(keys_and_cert['keyPair']['PrivateKey'])
            logger.debug(
                'Finished writing private key to file %s.', private_key_path)

        with open(public_key_path, 'w+') as public_key:
            public_key.write(keys_and_cert['keyPair']['PublicKey'])
            logger.debug('Finished writing public key to file %s.',
                         private_key_path)

        with open(certificate_path, 'w+') as certificate:
            certificate.write(keys_and_cert['certificatePem'])
            logger.debug(
                'Finished writing certificate to file %s.', certificate_path)

        # The certficate ARN will be required when adding the thing to
        # the AWS Greengrass core.
        result['certificateArn'] = keys_and_cert['certificateArn']

        # With the certificates and keys now saved locally, attach the
        # certificate ARN to the AWS IoT thing.
        iot_client.attach_thing_principal(
            thingName=result['name'],
            principal=result['certificateArn']
        )
        logger.debug('Attached thing %s to certificate %s',
                     result['name'], result['certificateArn'])

        if policy_name:
            new_policy = {
                'policyName': policy_name
            }
        else:
            # Creates a default policy (see above) and then attaches
            # the policy to the certificate.
            new_policy = iot_client.create_policy(
                policyName="{}Policy".format(new_thing['thingName']),
                policyDocument=DEFAULT_IOT_POLICY
            )
            logger.debug('Created new policy %s', new_policy['policyName'])

        iot_client.attach_policy(
            policyName=new_policy['policyName'],
            target=result['certificateArn']
        )
        logger.debug('Attached policy %s to certificate %s.',
                     new_policy['policyName'], result['certificateArn'])

    except ClientError as err:
        logger.error("Error while provisioning thing: %s", err)

    return result


def add_thing_to_greengrass(thing_info, greengrass_group_name):
    """
    Adds the specified thing to the AWS Greengrass group specified.
    :param thing_name: str Name of the AWS IoT Thing.
    :param greengrass_group_name: str Name of the AWS Greengrass core.
    """
    logger.info('Adding %s to AWS Greengrass core %s...',
                thing_info['name'], greengrass_group_name)
    try:
        greengrass_client = boto3.client('greengrass')

        greengrass_groups = greengrass_client.list_groups()

        # Filter out the matching group.
        group_details = next(iter(
            [g for g in greengrass_groups['Groups'] if g['Name'] == greengrass_group_name]), None)

        # Get the latest group version definition, which will be used to
        # get the latest device definition so the device can be appended
        # to the end of the current list.
        group_version = greengrass_client.get_group_version(
            GroupId=group_details['Id'],
            GroupVersionId=group_details['LatestVersion']
        )
        logger.debug("Found latest group version %s", group_details['LatestVersion'])

        device_def_id, device_def_version_id = __parse_device_def_arn(
            group_version['Definition']['DeviceDefinitionVersionArn'])

        # Gets what should be the latest version of the device definition.
        device_definition = greengrass_client.get_device_definition_version(
            DeviceDefinitionId=device_def_id,
            DeviceDefinitionVersionId=device_def_version_id
        )

        new_devices = list(device_definition['Definition']['Devices'])

        # Add the device created or identified earlier and add the device
        # to the list of current devices.
        new_devices.append({
            'CertificateArn': thing_info['certificateArn'],
            'ThingArn': thing_info['arn'],
            'SyncShadow': True,
            'Id': str(uuid.uuid4())
        })
        logger.debug('New device list is: %s', new_devices)

        # Create a new device definition with the new list of devices.
        new_device_definition = greengrass_client.create_device_definition_version(
            DeviceDefinitionId=device_definition['Id'],
            Devices=new_devices
        )
        logger.debug('Finished adding the new device to the definition.')

        group_version_args = {
            'GroupId': group_version['Id'],
            'CoreDefinitionVersionArn': group_version['Definition'].get(
                'CoreDefinitionVersionArn', None),
            'DeviceDefinitionVersionArn': new_device_definition['Arn'],
            'FunctionDefinitionVersionArn': group_version['Definition'].get(
                'FunctionDefinitionVersionArn', None),
            'LoggerDefinitionVersionArn': group_version['Definition'].get(
                'LoggerDefinitionVersionArn', None),
            'ResourceDefinitionVersionArn': group_version['Definition'].get(
                'ResourceDefinitionVersionArn', None),
            'SubscriptionDefinitionVersionArn': group_version['Definition'].get(
                'SubscriptionDefinitionVersionArn', None)
        }

        # This is getting the arguments from above that actually have values,
        # otherwise the call to create the new group version will fail.
        greengrass_client.create_group_version(
            **{k:v for k, v in group_version_args.iteritems() if v}
        )

        logger.debug('Finished updating Greengrass core with new thing.')

    except ClientError as err:
        logger.error("Error while provisioning thing: %s", err)


if __name__ == '__main__':
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(format=FORMAT)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logger.debug('Starting main...')

    # pylint: disable=C0103
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--thing-name", required=True,
                        help="Name of the AWS IoT thing to use.")
    parser.add_argument(
        "-p", "--path", required=False,
        help="Path to save private key, public key, and certificate for the thing.")
    parser.add_argument("-g", "--greengrass-core-name",
                        required=False, help="Name of the AWS Greengrass core.")
    parser.add_argument("--policy", required=False,
                        help="The name of an existing IoT policy to use.")
    args = parser.parse_args()
    thing_details = get_thing_details(args.thing_name)

    if not thing_details:
        out_dir = args.path or os.getcwd()
        private_key_out = os.path.join(
            out_dir, "{}.priv.key".format(args.thing_name))
        public_key_out = os.path.join(
            out_dir, "{}.pub.key".format(args.thing_name))
        certificate_out = os.path.join(
            out_dir, "{}.cert.pem".format(args.thing_name))
        thing_details = provision_thing(
            args.thing_name, private_key_out, public_key_out, certificate_out, args.policy)

    if args.greengrass_core_name:
        add_thing_to_greengrass(thing_details, args.greengrass_core_name)
    # pylint: enable=C0103
