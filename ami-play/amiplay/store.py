"""Session store for the AMI Play CLI: credentials, device UUID, checked-in venue, last geocode.

Everything lives in one JSON file (default: ../secrets/session.json, gitignored). The file is
written 0600 because the authentication token is as good as the password while it lives.

INVARIANTS:
- ``device_uuid`` is generated once per session file and never regenerated; the server keys
  check-in state on it, so a new value every run would leave ghost check-ins behind.
- ``save()`` never writes a partial file: it writes a temp file and renames over the target.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "secrets" / "session.json"


class Session:
    def __init__(self, path: Path | str | None = None):
        env_path = os.environ.get("AMI_PLAY_SESSION")
        self.path = Path(path or env_path or DEFAULT_PATH)
        self.data: dict[str, Any] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                self.data = {}
        if not self.data.get("deviceUUID"):
            self.data["deviceUUID"] = str(uuid.uuid4())
            self.save()

    # -- persistence -------------------------------------------------------------------------

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".session-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # -- identity ----------------------------------------------------------------------------

    @property
    def env(self) -> str:
        return self.data.get("env", "prod")

    @env.setter
    def env(self, value: str) -> None:
        self.data["env"] = value

    @property
    def device_uuid(self) -> str:
        return self.data["deviceUUID"]

    @property
    def player_id(self) -> int | None:
        return self.data.get("playerId")

    @property
    def auth_token(self) -> str | None:
        return self.data.get("authentication")

    @property
    def logged_in(self) -> bool:
        return self.player_id is not None and bool(self.auth_token)

    def set_login(self, player_id: int, token: str, email: str | None = None) -> None:
        self.data["playerId"] = int(player_id)
        self.data["authentication"] = token
        if email:
            self.data["email"] = email

    def clear_login(self) -> None:
        for key in ("playerId", "authentication", "email", "username", "checkedIn"):
            self.data.pop(key, None)

    # -- venue / geocode ---------------------------------------------------------------------

    @property
    def checked_in(self) -> dict[str, Any] | None:
        return self.data.get("checkedIn")

    @checked_in.setter
    def checked_in(self, value: dict[str, Any] | None) -> None:
        if value is None:
            self.data.pop("checkedIn", None)
        else:
            self.data["checkedIn"] = value

    @property
    def geocode(self) -> dict[str, float] | None:
        return self.data.get("geocode")

    @geocode.setter
    def geocode(self, value: dict[str, float] | None) -> None:
        if value is None:
            self.data.pop("geocode", None)
        else:
            self.data["geocode"] = {"lat": float(value["lat"]), "lng": float(value["lng"])}
