#!/bin/bash
# launchd entrypoint. We go through /bin/bash (which has the TCC/Full-Disk grant
# the other harness watchers rely on) so the python child can read scripts under
# ~/Documents; calling /usr/bin/python3 directly from launchd is denied.
cd "/Users/alexhedtke/Documents/Exobrain harness/airdrop-to-console" || exit 1
exec /usr/bin/python3 watch.py
