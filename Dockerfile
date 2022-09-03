FROM python:3-alpine

# Install deps
RUN apk add -U g++ gcc make \
&& pip install pyyaml influxdb-client PyP100 python-kasa \
&& apk del g++ gcc make


# Copy the script up
COPY app /app

# Set config file location
ENV CONF_FILE /config.yml

CMD /app/collect.py
