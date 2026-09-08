"""espncli: the read-only ESPN client behind fantasy/bin/espn.

Two hosts, one invariant. The fantasy league API (lm-api-reads) needs Alex's
session cookies and is where rosters, matchups, projections, the wire, and
the activity feed live. The public NFL API (site.web.api.espn.com) needs no
cookies and supplies the slate, odds, weather, injuries, and player news.
Nothing in this package writes to ESPN; see client.py for the invariants.
"""
