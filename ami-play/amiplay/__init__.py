"""amiplay: an unofficial client for the AMI Play jukebox service.

The wire format was recovered from the Android app (com.amientertainment.AMISmartBar 5.2.0);
see ../README.md for the endpoint map and the rules the server enforces.
"""

from amiplay.api import AmiClient, AmiError, ENVIRONMENTS, RESULT_CODES, SELECTION_CODES
from amiplay.store import Session

__all__ = ["AmiClient", "AmiError", "ENVIRONMENTS", "RESULT_CODES", "SELECTION_CODES", "Session"]
