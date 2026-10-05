# matter

A Matter controller for this computer. It uses the [matter.js](https://github.com/project-chip/matter.js) shell (`@matter/nodejs-shell`, Apache-2.0), which does the same work as `chip-tool` from the Matter SDK.

The controller joins a device as an extra admin, next to Google Home or another hub. The hub keeps its control. The first use is to set the on/off transition time of lights to 0.

## Setup

Run `npm install` in this folder. `bin/matter` runs it on the first call if `node_modules` is missing.

## Usage

```
bin/matter "nodes list"
bin/matter --timeout 120 "commission pair --pairingCode <11-digit code>"
bin/matter "attributes levelcontrol read all <node> 1"
bin/matter "attributes levelcontrol write onofftransitiontime 0 <node> 1"
```

Each argument is one shell command. `bin/matter` sends it, waits for the shell's `Done.` line, then sends the next.

## Pairing codes

A device that is already in a hub must get a pairing code from that hub. In Google Home, open the device, then Settings > Linked Matter apps & services > Link apps & services > Use pairing code. A code is valid for approximately 15 minutes.

## Storage

The controller's fabric, keys, and node list are in `~/.matter/shell-0`, outside the repo. If you delete that folder, the computer loses its admin access to every device that it paired.
