# govee/data

`devices.json` is gitignored. It records the IP, SKU, and alias of each Govee bulb on the home network.

To make it again, run `govee/bin/govee scan`. Then give each bulb a name with `govee/bin/govee name <id-tail> <alias>`.

Optional fields for each bulb: `group` (bulbs that always have the same state), `room` (the Google Home room), and `floor` (a target for all the rooms on one floor).
