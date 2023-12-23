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
import logging
import os
import sys
import time
import yaml

from influxdb_client.client.write_api import SYNCHRONOUS
from kasa import SmartPlug
from PyP100 import PyP110

CONF_FILE = os.getenv("CONF_FILE", "example/config.yml")
log = logging.getLogger(__name__)
#logging.basicConfig(level=logging.DEBUG)

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
            log.error("Err: Persistent mode enabled, but interval not defined")
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
        log.error("Error: Neither kasa or tapo devices have been defined")
        sys.exit(1)

    if "kasa" in config:
        for kasa in config["kasa"]["devices"]:
            now_usage_w, today_usage = poll_kasa(kasa['ip'])
            if now_usage_w is False:
                print(f"Failed to communicate with device {kasa['name']}")
                continue
            
            if today_usage is False:
                print(f"Plug: {kasa['name']} using {now_usage_w}W, today: Not Supplied")
            else:
                print(f"Plug: {kasa['name']} using {now_usage_w}W, today: {today_usage/1000} kWh")
                
                
            stats[kasa['name']] = {
                    "today_usage" : today_usage,
                    "now_usage_w" : now_usage_w,
                    "time" : start_time
                }
            
    if "tapo" in config:
        # Override the tapo logging level - the module calls logger.exception() if it fails to login to a device
        # The problem with that is, there are now 2 possible (and incompatible) auth schemes, so login may or may
        # not work - we don't really want log noise from something we're having to handle.
        tapo_log = logging.getLogger('PyP100')
        tapo_log.setLevel(logging.CRITICAL)
                
        for tapo in config["tapo"]["devices"]:
            # Set a sane default for auth mode if it's not been specified
            if "auth" not in tapo:
                tapo['auth'] = "all"
                
            now_usage_w, today_usage = poll_tapo(
                tapo['ip'], 
                config["tapo"]["user"], 
                config["tapo"]["passw"],
                tapo['auth']
                )
            
            if now_usage_w is False:
                print(f"Failed to communicate with device {tapo['name']}")
                continue

            if today_usage is False:
                print(f"Plug: {tapo['name']} using {now_usage_w}W, today: Not Supplied")
            else:
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
    except Exception as e:
        log.debug(f"Failed to connect to plug: {e}")
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
    try:
        now_usage_w = usage_dict["power_mw"] / 1000
    except Exception as e:
        # An error occurred, let the caller handle it
        log.error(f'Err: failed to calculate {usage_dict["power_mw"]}  / 1000')
        log.debug(f"Encountered exception: {e}")
        return False, False

    return now_usage_w, today_usage



def poll_tapo_newauth(ip, user, passw):
    ''' Attempt to poll a TP-Link Tapo smartplug using the default auth mechanism
    
    If the original PyP100 module is in use this will be the "old" auth mechanism 
    which doesn't work with devices running firmware version >= 1.2.1
    
    If the new PyP100 fork is in use, this will be the new KLAP mechanism which works
    with firmware version >= 1.2.1. However, it will fail for devices running older
    firmware
    
    utilities/tp-link-to-influxdb#7
    
    This function is expected to work with
    
    - new PyP100 fork and devices running firmware >= 1.2.1
    - original PyP100 module and devices running firmware < 1.2.1

    '''
    
    # Start by seeing whether we can force the auth type - this'll only work for the
    # new fork, so if we get an exception we just don't force it
    try:
        p110 = PyP110.P110(ip, user, passw, preferred_protocol="new")
                
    except:
        p110 = PyP110.P110(ip, user, passw)
    
    try:
        p110.handshake() #Creates the cookies required for further methods
        p110.login() #Sends credentials to the plug and creates AES Key and IV for further methods
    except Exception as e:
        log.debug(f"NewAuth Failed at login stage {e}")
        return False
    
    # If we got this far, we've connected to the device successfully
    # get the readings
    try:
        usage_dict = p110.getEnergyUsage()
    except Exception as e:
        log.debug(f"NewAuth Failed at reading stage {e}")
        return False
    
    
    return usage_dict
    

def poll_tapo_old_auth(ip, user, passw):
    ''' Try polling a TP-Link tapo device forcing "old" authentication.
    
    This will only work if the new PyP100 fork is in use - otherwise the module
    will complain about invalid variables
    
    This function is expected to work with
    
    - new PyP100 fork and devices running firmware < 1.2.1
    
    '''
    
    try:
        p110 = PyP110.P110(ip, user, passw, preferred_protocol="old")
        p110.handshake() #Creates the cookies required for further methods
        p110.login() #Sends credentials to the plug and creates AES Key and IV for further methods        
    except Exception as e:
        log.debug(f"OldAuth Failed at login stage {e}")
        return False

    # If we got this far, we've connected to the device successfully
    # get the readings
    try:
        usage_dict = p110.getEnergyUsage()
    except Exception as e:
        log.debug(f"OldAuth Failed at reading stage {e}")
        return False
    
    return usage_dict
    
    
def poll_tapo(ip, user, passw, auth_mode):
    ''' Poll a TP-Link Tapo smartplug
    
    auth_mode should be one of
    
    - all: try modes in turn
    - package_defaults: only try the package defaults (new for almottier, normal for PyPi)
    - almottier_old: only try old auth via the almottier fork
    
    Note: setting almottier_old when using the PyPi P100 will fail    
    '''
    
    log.debug(f"Auth mode is set to {auth_mode}")

    # If the provided auth_mode allows it, try the package 
    usage_dict = False
    if auth_mode != 'almottier_old':
        usage_dict = poll_tapo_newauth(ip, user, passw)
        

    if not usage_dict and auth_mode != 'package_defaults':
        # Polling failed, try old auth mechanism
        usage_dict = poll_tapo_old_auth(ip, user, passw)
        
    if not usage_dict:
        # We still haven't got anything - device may be unreachable
        return False, False
    

    # The response to getEnergyUsage differs between the two libraries. The older library
    # nested things under a result attribute, the new one does not.
    
    # Check that we got *something* back
    if not usage_dict:
        # We failed to elicit a response
        return False, False

    # Now figure out whether it's a new format response or old
    if "result" not in usage_dict and "today_energy" in usage_dict:
        # It's new style. Map it over to the new format
        d = { "result" : usage_dict }
        usage_dict = d
        
    # Finally, double check that the dict, whether re-mapped or not
    # has a result attribute
    if "result" not in usage_dict:
        return False, False

    today_usage = False
    if "today_energy" in usage_dict["result"]:
        today_usage = usage_dict["result"]["today_energy"]
       
    try:
        now_usage_w = usage_dict["result"]["current_power"] / 1000
    except Exception as e:
        log.error(f'Err: failed to calculate {usage_dict["result"]["current_power"]}  / 1000')
        log.debug(f"Encountered exception: {e}")
        return False, False
    
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
    except Exception as e:
        log.debug(f"Failed to write to InfluxDB: {e}")
        return False


if __name__ == "__main__":
    main()
