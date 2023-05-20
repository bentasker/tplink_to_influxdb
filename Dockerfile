FROM python:3-alpine

ENV PYTHONUNBUFFERED=1
# Install deps
RUN apk add -U g++ gcc make \
&& pip install pyyaml influxdb-client PyP100 python-kasa \
&& apk del g++ gcc make


# Copy the script up
COPY app /app

# Set config file location
ENV CONF_FILE /config.yml

CMD /app/collect.py

LABEL org.opencontainers.image.authors="github@bentasker.co.uk"
LABEL org.opencontainers.image.source https://github.com/bentasker/tplink_to_influxdb
LABEL org.opencontainers.image.title TP-Link Smartsocket to InfluxDB
LABEL org.opencontainers.image.description Polls power usage information from Tapo and Kasa smartplugs and writes to InfluxDB
LABEL org.opencontainers.image.licenses="BSD-3-Clause"
