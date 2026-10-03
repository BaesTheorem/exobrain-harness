# ups-track

Track a UPS package with no UPS account and no API keys. It is a CLI and a stdio MCP server.

## Why it exists

- The official UPS Tracking API (and the official `UPS-API/ups-mcp` server) needs OAuth keys. The UPS Developer Portal gives keys only to a person with a UPS shipper account number.
- ups.com sends an Akamai "Access Denied" page to curl, curl_cffi, and all headless browsers.
- A headed Chrome under [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) gets through. The tool opens Chrome with its window off-screen, loads the public tracking page, and reads the JSON that the page gets from `Track/GetStatus`.

## Use

```
ups-track/bin/ups-track 1Z...          # status and scan history
ups-track/bin/ups-track 1Z... --json   # the full GetStatus record
claude mcp add ups-track -s user -- "$PWD/ups-track/bin/ups-track" --mcp
```

The MCP server has one tool, `track_package(tracking_number)`.

## Requirements

- Google Chrome in `/Applications`, and `uv`. The script declares its dependencies inline (PEP 723), so `uv` installs them on the first run.
- The Chrome profile is in `~/.cache/ups-track/`.

## Limits

- Each lookup starts a Chrome window off-screen and takes approximately 10 to 20 seconds. Do not run it from an unattended job on a short interval.
- If UPS changes the page or the bot rules, the lookup fails with "ups.com sent no tracking data".
