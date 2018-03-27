#!/usr/bin/env bash

working_dir=$(pwd)

source ${working_dir}/settings.conf

python ${working_dir}/jobs_agent.py -n ${THING_NAME} -e ${IOT_ENDPOINT} -k ${PRIVATE_KEY_FILE} -r ${ROOT_CA_FILE} -c ${CERTIFICATE_FILE}

exit $?