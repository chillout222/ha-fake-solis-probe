FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    python3

COPY run.sh /run.sh
COPY fake_solis_probe.py /fake_solis_probe.py
COPY solis_probe /solis_probe
COPY requirements.txt /requirements.txt

RUN chmod a+x /run.sh

CMD ["/run.sh"]
