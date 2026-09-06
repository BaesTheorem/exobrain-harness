"""meetupcli: an unofficial client for meetup.com built on the website's own GraphQL endpoint.

Read-side calls (search, events, groups, locations) need no login. Personal calls take the
browser's session cookie. See ../README.md for the command surface and the wire quirks.
"""

from meetupcli.api import MeetupClient, MeetupError
from meetupcli.model import normalize_event, normalize_group, parse_event_ref, parse_group_ref

__all__ = [
    "MeetupClient",
    "MeetupError",
    "normalize_event",
    "normalize_group",
    "parse_event_ref",
    "parse_group_ref",
]
