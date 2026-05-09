#!/bin/bash
# Reconcile job-listing frontmatter on file changes.
# Triggered by launchd (com.exobrain.job-listings-sync) when files in
# Projects/Get new job/Job Listings/ change, with a periodic safety-net interval.

set -euo pipefail

cd "$(dirname "$0")"

/usr/bin/env python3 reconcile.py
