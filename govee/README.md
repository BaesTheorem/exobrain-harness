# govee

A CLI that controls Govee lights on the local network through the Govee LAN API (UDP). It uses the [govee-local-api](https://github.com/Galorhallen/govee-local-api) library, which is also the library of the Home Assistant integration.

## Setup

1. In the Govee app, open each light, open its settings, and turn on **LAN Control**.
2. Run `bin/govee scan`. The first run makes `.venv` and installs `requirements.txt`.
3. Give each bulb a name: `bin/govee name 3F:F4 desk`.

## Commands

```
govee scan                      discover bulbs and show status
govee status [TARGET]
govee on|off [TARGET]
govee brightness PCT [TARGET]
govee color COLOR [TARGET]      red, #ff8800, 255,136,0, or warm/cool/daylight
govee temp KELVIN [TARGET]
govee name DEVICE ALIAS
govee sync-names                copy the Govee app names into the aliases (needs GOVEE_API_KEY in the harness .env)
govee google-script [--room R]    print a Google Home script for the power-on rule (skips bulbs with no room)
govee --check <command>         read the status back after a set command
```

TARGET is `all` (the default), an alias, an alias group (`vanity` selects `vanity-1` to `vanity-4`), an IP, or the last part of the device id. Use commas for more than one target.

## Limits

- The LAN API does not acknowledge a set command. Use `--check` to make sure that the command had an effect.
- The LAN API cannot start scenes on basic bulbs such as the H6008. You must use the cloud API for scenes.
- A bulb does not reply when the wall switch is in the OFF position.

## Power-on color rule

`govee google-script` writes a script for the Google Home script editor (home.google.com > Automations > Add > script). Each bulb gets three automations. When the bulb turns on, Google sets its color and brightness for the time of day:

| Period | Color | Brightness |
| --- | --- | --- |
| Sunrise to 2 hours before sunset | 6500 K | 100% |
| The 2 hours before sunset | 2700 K | 100% |
| Sunset to sunrise | red | 30% |

6500 K is the coolest white the H6008 makes and gives the most alertness. 2700 K is its warmest white (the API advertises 2000 K, but the bulb clamps a lower value to 2700 K). Red light has almost no effect on melatonin. The rule runs in the Google cloud, so it does not need this computer.

Google names a device "<name> - <room>". Give the room with `--room`, or add a `room` field to a bulb in `data/devices.json`.

