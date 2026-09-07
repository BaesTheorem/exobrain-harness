# kqi/secrets (gitignored)

Runtime credentials for the KQi scooter CLI. Nothing here is committed.

- `session.json` -- NIU cloud session written by `kqi login <account>`: access token,
  refresh token, expiry, app id, and a few account fields. Mode 0600.
- `scooter.json` -- written by `kqi setup`: the vehicle's serial number, product type,
  and its Bluetooth credentials from `v5/ble/bleinfo` (MAC, `blePassword`, `bleAes`,
  `bleSign`, `bleName`, `bus_protocol_type`), plus `cb_address`, the CoreBluetooth
  identifier the scooter was last seen under (macOS hides real MACs).

Rebuild both by running `kqi login you@example.com` then `kqi setup`. The vehicle has
to be bound to that NIU account in the NIU app first, because the cloud only hands the
Bluetooth password to a bound account.
