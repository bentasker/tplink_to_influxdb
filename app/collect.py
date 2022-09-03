#!/usr/bin/env python3
#
#
#
# pip install pyyaml influxdb-client PyP100 python-kasa

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


    stats = {}
    start_time = time.time_ns()

    for kasa in config["kasa"]["devices"]:
        now_usage_w, today_usage = poll_kasa(kasa['ip'])
        if now_usage_w is False:
            print(f"Failed to communicate with device {kasa['name']}")
            continue
        
        print(f"Plug: {kasa['name']} using {now_usage_w}W, today: {today_usage/1000} Wh")
        stats[kasa['name']] = {
                "today_usage" : today_usage,
                "now_usage_w" : now_usage_w,
                "time" : start_time
            }


    for tapo in config["tapo"]["devices"]:
        now_usage_w, today_usage = poll_tapo(tapo['ip'], config["tapo"]["user"], config["tapo"]["passw"])
        if now_usage_w is False:
            print(f"Failed to communicate with device {tapo['name']}")
            continue
        
        print(f"Plug: {tapo['name']} using {now_usage_w}W, today: {today_usage/1000} Wh")
        stats[tapo['name']] = {
                "today_usage" : today_usage,
                "now_usage_w" : now_usage_w,
                "time" : start_time
            }
        
   
    # Iterate through the InfluxDB connections and send the data over
    for influx in influxes:
        sendPointsToDest(influx, stats)

        
def poll_kasa(ip):
    ''' Poll a TP-Link Kasa smartplug
    
    TODO: need to add some exception handling to this
    '''
    p = SmartPlug(ip)
    asyncio.run(p.update())
    
    usage_dict = p.emeter_realtime
    today_usage = p.emeter_today
    
    # emeter_today seems to be quite racey, sometimes returning 0 sometimes returning 0.001
    # wh usage since it was powered on (at time of writing) is 80.
    # 
    # probably better to just omit the metric for now.
    #
    # It _may_ be because I've blocked the device from WAN access - https://github.com/home-assistant/core/issues/45436#issuecomment-766454897
    # sounds like it needs NTP access to be able to track this.
    #
    # Allowing UDP 123 out seems to have resolved it
    #today_usage = False
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
    

def sendPointsToDest(dest, points):
    ''' Iterate through the collected stats and write them out to InfluxDB
    '''
    write_api = dest['conn'].write_api(write_options=SYNCHRONOUS)
    for point in points:
        res = sendToInflux(write_api,
                     dest['bucket'],
                     dest['org'],
                     point, 
                     points[point]['now_usage_w'], 
                     points[point]['today_usage'],
                     points[point]['time']
                     )
        if not res:
            print(f"Failed to send point to {dest['name']}")

def sendToInflux(write_api, bucket, org, name, watts, today_kwh, timestamp):
    ''' Take a set of values, and send them on to InfluxDB
    '''
    today_w = False
    if today_kwh:
        # Our DB uses Wh rather that kWh so need to convert
        today_w = today_kwh * 1000

    try:
        p = influxdb_client.Point("power_watts").tag("host", name).field("consumption", int(float(watts)))
        write_api.write(bucket=bucket, org=org, record=p)
        
        if today_w:        
            p = influxdb_client.Point("power_watts").tag("host", name).field("watts_today", int(float(today_w)))
            write_api.write(bucket=bucket, org=org, record=p)

        return True
    except:
        return False
    
    


if __name__ == "__main__":
    main()
