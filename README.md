# TP-Link Smartplugs to InfluxDB

Background
------------

This is a small docker image to poll TP-Link Kasa and Tapo smart-plugs to retrieve energy usage readings and send them into InfluxDB.

In effect, this is an amalgamated and tidied version of scripts that I've previously published:

- [TP-Link Kasa polling script](https://www.bentasker.co.uk/posts/blog/house-stuff/739-monitoring-our-electricity-usage-with-influxdb.html#MonitoredPlugSockets)
- [TP-Link Tapo polling script](https://www.bentasker.co.uk/posts/blog/house-stuff/how-much-more-energy-efficient-is-eco-mode-on-a-dish-washer.html#tapo)

A detailed example of usage can be seen in ["Energy usage Monitoring With TP-Link Smart Sockets and InfluxDB"](https://www.bentasker.co.uk/posts/blog/house-stuff/capturing-energy-usage-info-with-tapo-kasa-and-influxdb.html)

----

## Usage

Configuration
---------------

Configuration is achieved via a YAML file, there's an example to get you started in [example/config.yml](example/config.yml)

The config file contains 4 sections

- poller
- tapo
- kasa
- influxdb

The `poller` section contains configuration information for the polling script itself
```yaml
poller:
    # If true, run in an infinite loop
    persist: true
    # Interval in seconds between runs
    interval: 20

```

Each of the remaining sections can have multiple devices:
```yaml
tapo:
    # Tapo devices require that you log in with the credentials
    # that you use to log into the app
    #
    user: "me@mymail.com"
    passw: "mysecretpass"
    devices:
        - 
            name: "washing-machine"
            ip : 192.168.3.152
        
        - 
            name: "big-fridge"
            ip : 192.168.3.153
```

Once collected, stats will be written to all listed InfluxDB outputs:

```yaml
influxdb:
    -
        name: "Cloud"
        url: "https://foo.example.com"
        token: "aaabbbccc=="
        org: "my org"
        bucket: "telegraf"
        
    - 
        name: "local"
        url: "http://192.168.3.84:8086"
        token: ""
        org: ""
        bucket: "testing_db"
```

Outputs are written using the v2 API, so the upstream can be any of the following

- InfluxDB OSS/Enterprise >= 1.8.0 
- InfluxDB OSS 2.x
- [InfluxDB Cloud](https://cloud2.influxdata.com)
- Telegraf (with [influxdb_v2_listener](https://github.com/influxdata/telegraf/tree/master/plugins/inputs/influxdb_v2_listener))

----

### Invocation

The container is currently designed to be invoked via cron (although [utilities/tp-link-to-influxdb#4](https://projects.bentasker.co.uk/gils_projects/issue/utilities/tp-link-to-influxdb/4.html) added the option of using a persistent container with an internal timer)

The configuration file needs to be exported into the container at `/config.yml` (if for some reason you wish to override this, you can use the environment variable `CONF_FILE` to tell the script where to find the config file)

```sh
docker run --rm \
--name="tplink_to_influxdb" \
-v $PWD/config.yml:/config.yml \
bentasker12/tplink_to_influxdb:latest
```

----

### Output

The script will write into a measurement called `power_watts`

Tags:

- `host`: the name of the monitored device

Fields:

- `consumption`: current reading (unit: W)
- `watts_today`: reported usage today (Wh)


----

### Running Without Docker

Although `docker` is the easiest way to run the script, it can also be run directly once you've installed a few dependencies.

You'll need `gcc`, `g++` and `make` installed: one of the dependencies is itself dependant on [PycryptoDome](https://www.pycryptodome.org) which includes some bits which need compiling.

```sh
sudo apt-get install build-essential
sudo pip install pyyaml influxdb-client PyP100 python-kasa
```

You'll need to tell the script where to find the config file
```sh
export CONF_FILE="/path/to/config"
```

And then, finally, invoke the script
```sh
app/collect.py
```


----

## Other Stuff

Device Support
-----------------

I use Tapo P110s and Kasa KP115's, so this is known to definitely work with those.

You can check whether your device is supported by looking at the support matrix on the underlying libraries

- [python-kasa](https://github.com/python-kasa/python-kasa#supported-devices)
- [TapoP100](https://github.com/fishbigger/TapoP100#tapo-p100)


----

Tapo vs Kasa
---------------

If you're planning a setup you may be trying to decide which devices to buy.

Tapo is the newer family, so you'll get better/longer support in the app. **But** they also have a more complicated authentication model, which is reliant on external connectivity (at the script's end - you can still restrict the plug's connectivity once you've provisioned it).

Kasa plugs are more expensive and (increasingly) harder to get hold off. However, they support fully local comms.

Given the choice, personally, I'd buy Kasa every time.


----

### License

Copyright (c) 2023 Ben Tasker.

Released under [BSD-3-Clause](LICENSE)


