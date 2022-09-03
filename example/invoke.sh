#!/bin/bash
#
# Example invocation
#
#

docker pull bentasker12/tplink_to_influxdb:latest
docker run --rm --name="tplink_to_influxdb" -v $PWD/config.yml:/config.yml bentasker12/tplink_to_influxdb:latest
