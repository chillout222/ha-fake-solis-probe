#!/usr/bin/with-contenv bashio
set -euo pipefail

mkdir -p /share/fake_solis_probe
touch /share/fake_solis_probe/events.jsonl

bashio::log.info "Starting Fake Solis Probe"
bashio::log.info "Structured JSONL log: /share/fake_solis_probe/events.jsonl"

python3 -u /fake_solis_probe.py
