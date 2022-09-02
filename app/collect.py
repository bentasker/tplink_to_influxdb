#!/usr/bin/env python3
#
#
#
# pip install pyyaml influxdb-client PyP100 python-kasa

import asyncio
import os
import sys
import yaml
import influxdb_client

from influxdb_client.client.write_api import SYNCHRONOUS
from kasa import SmartPlug
from PyP100 import PyP110



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

    for tapo in config["tapo"]["devices"]:
        now_usage_w, today_usage = poll_tapo(tapo['ip'], config["tapo"]["user"], config["tapo"]["passw"])
        if not now_usage_w:
            print(f"Failed to communicate with device {tapo['ip']}")
            continue
        
        print(f"Plug: {tapo['name']} using {now_usage_w}W, today: {today_usage/1000} Wh")
        

def poll_tapo(ip, user, passw):
    ''' Poll a TP-Link Tapo smartplug
    '''
    
    try:
        p110 = PyP110.P110(ip, user, passw)
        p110.handshake() #Creates the cookies required for further methods
        p110.login() #Sends credentials to the plug and creates AES Key and IV for further methods        
        usage_dict = p110.getEnergyUsage()
    except:
        return False, False

    today_usage = usage_dict["result"]["today_energy"]
    now_usage_w = usage_dict["result"]["current_power"] / 1000
                                                    
    return now_usage_w, today_usage
    




if __name__ == "__main__":
    main()
