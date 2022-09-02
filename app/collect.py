#!/usr/bin/env python3
#
#
#
# pip install pyyaml influxdb-client

import asyncio
import os
import sys
import yaml
import influxdb_client

from influxdb_client.client.write_api import SYNCHRONOUS



CONF_FILE = os.getenv("CONF_FILE", "example/config.yml")


def load_config():
    ''' Read the config file
    
    '''
    with open(CONF_FILE) as file:
        try:
            config = yaml.safe_load(file)
        except yaml.YAMLError as e:
            print(e)
            config = False
            
    return config
    

def main():
    ''' Main Entry point
    
    Read the config, initialise readers etc
    '''

    config = load_config()
    if not config:
        sys.exit(1)
    
    print(config)
    # Create the InfluxDB clients
    influxes = []

    for influx in config["influxdb"]:
            c = influxdb_client.InfluxDBClient(
                url = influx["url"],
                token = influx["token"],
                org = influx["org"]
            )
            influxes.append(c)

        


if __name__ == "__main__":
    main()
