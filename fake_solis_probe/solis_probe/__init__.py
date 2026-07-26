"""Fake Solis Probe for Home Assistant OS.

Emulates a Solis S6-EH1P hybrid inverter via Modbus TCP on port 502.
Reads real PV data from configurable Home Assistant sensors via Supervisor API
and serves it to Tibber Bridge. Battery registers return safe zero values.
"""
