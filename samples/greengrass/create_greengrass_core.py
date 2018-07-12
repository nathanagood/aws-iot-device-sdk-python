
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

from add_device_to_group import provision_thing, get_thing_details

# pylint: disable=C0103
logger = logging.getLogger()
# pylint: enable=C0103
logger.setLevel(logging.DEBUG)


def provision_greengrass_device(gg_group_name, gg_core_name=None,
                                core_policy_name=None, gg_key_cert_path=None):
    """
    Provisions a new AWS Greengrass device using the given core and group names
    and saves the keys and certificates locally.
    :param gg_group_name: str Name of the AWS Greengrass group
    :param gg_core_name: str Name of the AWS Greengrass core. If not supplied, it will
                          be generated from the core name
    :param core_policy_name: str Name of the policy to create for the IoT Core device
    :param gg_key_cert_path: str Output path in which to store the generated keys and certs.
    """
    logger.info("Provisioning AWS Greengrass core with name %s...", gg_core_name)
    greengrass_client = boto3.client('greengrass')
    try:

        greengrass_group = greengrass_client.create_group(
            Name=gg_group_name
        )

        cert_authority = greengrass_client.create_group_certificate_authority(
            GroupId=greengrass_group['Id']
        )

        core_name = gg_core_name or "{}_Core".format(gg_group_name)
        out_dir = gg_key_cert_path or os.getcwd()
        core_private_key = os.path.join(
            out_dir, "{}.priv.key".format(core_name))
        core_public_key = os.path.join(
            out_dir, "{}.pub.key".format(core_name))
        core_cert = os.path.join(
            out_dir, "{}.cert.pem".format(core_name))

        provision_thing(core_name, core_private_key,
                        core_public_key, core_cert, core_policy_name)

        core_details = get_thing_details(core_name)

        core_definition = greengrass_client.create_core_definition(
            Name=core_name,
            InitialVersion={
                'Cores': [
                    {
                        'Id': str(uuid.uuid4()),
                        'CertificateArn': core_details['certificateArn'],
                        'ThingArn': core_details['arn'],
                        'SyncShadow': True
                    }
                ]
            }
        )

        greengrass_client.create_group_version(
            GroupId=greengrass_group['Id'],
            CoreDefinitionVersionArn=core_definition['LatestVersionArn']
        )

    except ClientError as err:
        logger.error(
            "Error while provisioning the AWS Greengrass device: %s", err)


if __name__ == '__main__':
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(format=FORMAT)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logger.debug('Starting main...')

    # pylint: disable=C0103
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-name", required=True,
                        help="Name of the AWS Greengrass core.")
    parser.add_argument("--group-name", required=False,
                        help="Name of the AWS Greengrass group.")
    parser.add_argument("--key-path", required=False,
                        help="Path to a local folder in which to save the keys and certificates.")
    parser.add_argument("--policy", required=False,
                        help="The name of an existing IoT policy to use.")
    args = parser.parse_args()
    # pylint: enable=C0103

    provision_greengrass_device(
        args.core_name,
        args.group_name,
        args.policy,
        args.key_path
    )
