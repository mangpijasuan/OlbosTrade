# IBKR Client Portal Web API gateway (clientportal.gw), vendored.
# Runs headless on the droplet; authenticate once via browser (see README.md).
#
# Build context is this directory (deploy/clientportal). The gateway ships its
# own 3rd-party jars under build/lib and the runner under dist/.
FROM eclipse-temurin:21-jre

# curl is used by the compose healthcheck against the local :5000 endpoint
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /gateway

# Copy the vendored gateway distribution
COPY bin/  ./bin/
COPY build/ ./build/
COPY dist/ ./dist/
COPY root/ ./root/

RUN chmod +x bin/run.sh

# Gateway listens on 5000 (HTTPS, self-signed cert from root/vertx.jks)
EXPOSE 5000

# Launch via the official runner from the gateway root.
CMD ["bash", "bin/run.sh", "root/conf.yaml"]
