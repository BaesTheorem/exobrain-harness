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
govee --check <command>         read the status back after a set command
```

TARGET is `all` (the default), an alias, an alias group (`vanity` selects `vanity-1` to `vanity-4`), an IP, or the last part of the device id. Use commas for more than one target.

## Limits

- The LAN API does not acknowledge a set command. Use `--check` to make sure that the command had an effect.
- The LAN API cannot start scenes on basic bulbs such as the H6008. You must use the cloud API for scenes.
- A bulb does not reply when the wall switch is in the OFF position.
