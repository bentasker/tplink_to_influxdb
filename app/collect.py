#!/usr/bin/env python3
#
# Poll TP-Link smart-plugs for energy usage readings and send into InfluxDB
#
# pip install pyyaml influxdb-client PyP100 python-kasa
#
# Copyright (c) 2023 B Tasker
#
# Released under BSD-3-Clause License, see LICENSE in the root of the project repo
#

import asyncio
import influxdb_client
import os
import sys
import time
import yaml

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

    # Create the InfluxDB clients
    influxes = []

    for influx in config["influxdb"]:
            c = influxdb_client.InfluxDBClient(
                url = influx["url"],
                token = influx["token"],
                org = influx["org"]
            )
            influxes.append({"name": influx['name'],
                             "bucket": influx["bucket"],
                             "conn": c,
                             "org" : influx["org"]
                             })

    
    # Should we be running an infinite loop?
    persist = False
    if "poller" in config and "persist" in config['poller']:
        if "interval" not in config["poller"]:
            print("Err: Persistent mode enabled, but interval not defined")
        else:
            persist = True
        
    if not persist:
        # Trigger the poller as a one-shot thing
        do_work(config, influxes)
        return
    
    # Otherwise, set up a loop and poll periodically
    while True:
        do_work(config, influxes)
        time.sleep(int(config["poller"]["interval"]))


def do_work(config, influxes):
    ''' Trigger polls of the various devices and push resulting metrics
        
    '''
    stats = {}
    start_time = time.time_ns()

    if "kasa" not in config and "tapo" not in config:
        print("Error: Neither kasa or tapo devices have been defined")
        sys.exit(1)

    if "kasa" in config:
        for kasa in config["kasa"]["devices"]:
            now_usage_w, today_usage = poll_kasa(kasa['ip'])
            if now_usage_w is False:
                print(f"Failed to communicate with device {kasa['name']}")
                continue
            
            if today_usage:
                print(f"Plug: {kasa['name']} using {now_usage_w}W, today: {today_usage/1000} kWh")
            else:
                print(f"Plug: {kasa['name']} using {now_usage_w}W, today: Not Supplied")
                
            stats[kasa['name']] = {
                    "today_usage" : today_usage,
                    "now_usage_w" : now_usage_w,
                    "time" : start_time
                }
            
    if "tapo" in config:
        for tapo in config["tapo"]["devices"]:
            now_usage_w, today_usage = poll_tapo(tapo['ip'], config["tapo"]["user"], config["tapo"]["passw"])
            if now_usage_w is False:
                print(f"Failed to communicate with device {tapo['name']}")
                continue
            
            print(f"Plug: {tapo['name']} using {now_usage_w}W, today: {today_usage/1000} kWh")
            stats[tapo['name']] = {
                    "today_usage" : today_usage,
                    "now_usage_w" : now_usage_w,
                    "time" : start_time
                }
        
    # Build a buffer of points
    points_buffer = buildPointsBuffer(stats)
    
    if len(points_buffer) > 0:
        # Iterate through the InfluxDB connections and send the data over
        for dest in influxes:
            write_api = dest['conn'].write_api(write_options=SYNCHRONOUS)
            res = sendToInflux(write_api,
                        dest['bucket'],
                        dest['org'],
                        points_buffer
                        )
            if not res:
                print(f"Failed to send points to {dest['name']}")
            else:
                print(f"Wrote {len(points_buffer)} points to {dest['name']}")

        
def poll_kasa(ip):
    ''' Poll a TP-Link Kasa smartplug
    
    TODO: need to add some exception handling to this
    '''
    
    # Connect to the plug and receive stats
    try:
        p = SmartPlug(ip)
        asyncio.run(p.update())
    except:
        return False, False
            
    # emeter_today relies on external connectivity - it uses NTP to keep track of time
    # you need to allow UDP 123 outbound if you're restricting the plug's external connectivity
    # otherwise you'll get 0 or 0.001 back instead of the real value
    # 
    # See https://github.com/home-assistant/core/issues/45436#issuecomment-766454897
    #
    
    # See whether the socket returned daily readings
    today_usage = False
    if p.emeter_today:
        # Convert from kWh to Wh
        today_usage = p.emeter_today * 1000
        
    usage_dict = p.emeter_realtime
    
    # Convert to watts
    now_usage_w = usage_dict["power_mw"] / 1000

    return now_usage_w, today_usage


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
    

def buildPointsBuffer(points):
    ''' Iterate through the collected stats and write them out to InfluxDB
    '''
    
    # Initialize

    points_buffer = []
    
    for point in points:
             
        # Build a point    
        p = influxdb_client.Point("power_watts").tag("host", point).field("consumption", float(points[point]['now_usage_w'])).time(points[point]['time'])
        points_buffer.append(p)
        
        
        # If we've captured usage, add a point for that
        if points[point]['today_usage']:
            p = influxdb_client.Point("power_watts").tag("host", point).field("watts_today", int(float(points[point]['today_usage']))).time(points[point]['time'])
            points_buffer.append(p)
        
    return points_buffer


def sendToInflux(write_api, bucket, org, points_buffer):
    ''' Take a set of values, and send them on to InfluxDB
    '''
    try:
        write_api.write(bucket, org, points_buffer)
        return True
    except:
        return False


if __name__ == "__main__":
    main()
