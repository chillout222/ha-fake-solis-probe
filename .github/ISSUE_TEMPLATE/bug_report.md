---
name: Bug report
about: Report something that isn't working
title: "[BUG] "
labels: bug
assignees: ''

---

**Describe the bug**
A clear and concise description of what the bug is.

**Environment**
- Home Assistant version:
- HAOS version:
- Addon version (Fake Solis Probe):
- Solis inverter model:
- Datalogger model (e.g. S2-WL-ST):
- Tibber Bridge firmware (if known):

**Sensor configuration**
```
ha_sensor_pv_power: sensor.???
ha_sensor_grid_power: sensor.???
ha_sensor_total_energy: sensor.???
ha_sensor_daily_energy: sensor.???
grid_power_sign_convention: negate/direct
```

**Observed behavior**
What happened?

**Expected behavior**
What did you expect to happen?

**Addon logs**
```
Paste relevant lines from the addon Log tab here.
Remove any IP addresses or personal information before posting.
```

**events.jsonl snippet (if relevant)**
```json
Paste the last few lines from /share/fake_solis_probe/events.jsonl here.
Remove IP addresses before posting.
```

**Additional context**
Add any other context about the problem here.
