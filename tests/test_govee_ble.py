"""govee/govee_ble.py codec against wire captures of a real H6008.

The vectors come from damient/govee-toolkit (MIT): the H6008 captures in
tests/fixtures/ble-captures/H6008/encoded.txt (firmware 1.01.25) and the codec
tests in packages/rust/src/ble/encode.rs. A wrong seed or a wrong cipher stage
decodes no frame, and the bulb answers nothing, so these bytes are the only
cheap check that the port is exact.

The default pytest environment has no bleak or cryptography, so this file skips
there. Run it with:
    uv run --no-project --with pytest --with bleak --with cryptography pytest tests/test_govee_ble.py
"""

from typing import Any

import pytest
from conftest import load_script

pytest.importorskip("bleak")
pytest.importorskip("cryptography")
ble = load_script("govee/govee_ble.py")


def hx(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


SESSION = hx("d1 ff 2c 59 86 b4 e1 0e 3c 69 96 c4 f1 1e 4b 79")


def test_request_encodes_under_the_base_seed():
    plain = hx("e7 01 40 3c 92 24 d5 0c 2f 34 5c 71 ee 3b 8a 91 93 48 0d db")
    wire = hx("62 50 d9 65 7e 67 28 e3 d9 84 b1 78 90 23 de 6e fb a6 4d 84")
    base = ble.Codec(ble.BASE_SEED)
    assert base.encode(plain) == wire
    assert base.decode(wire) == plain


def test_answer_carries_the_session_seed():
    wire = hx("86 de b2 b9 88 89 88 3f cd 9f 73 9b d9 08 8c c8 23 97 4d e8")
    plain = ble.Codec(ble.BASE_SEED).decode(wire)
    assert plain[:2] == b"\xe7\x01"
    assert plain[2:18] == SESSION


def test_power_off_under_the_session_seed():
    plain = ble.frame(0x33, 0x01, 0x00)
    assert plain == hx("33 01" + " 00" * 17 + " 32")
    wire = hx("56 09 fb 54 ae 00 14 77 61 7a 47 b3 4b 10 11 0f 46 03 93 b6")
    assert ble.Codec(SESSION).encode(plain) == wire


def test_short_frame_takes_the_stream_stage_alone():
    assert ble.Codec(ble.BASE_SEED).decode(hx("cd ec 50 5e b7")) == hx("a5 02 10 01 b6")


def test_handshake_frame_checksum():
    f = ble.handshake_frame(0x02)
    assert len(f) == 20 and f[:2] == b"\xe7\x02"
    x = 0
    for b in f[:19]:
        x ^= b
    assert f[19] == x


def test_kelvin_rgb_is_warm_at_2700_and_white_at_6500():
    r, g, b = ble.kelvin_rgb(2700)
    assert r == 255 and g < 200 and b < g
    assert ble.kelvin_rgb(6500) == (255, 254, 250) or min(ble.kelvin_rgb(6500)) > 240


class FakeBulb:
    """A simulated H6008 that speaks the encoded link, as a BleakClient stand-in.

    Like the real bulb (bedroom-2, 2026-11-03), a brightness frame turns it on.
    """

    def __init__(self, on: bool):
        self.on, self.brightness = on, 30
        self.seed = bytes(range(16))
        self.base: Any = ble.Codec(ble.BASE_SEED)
        self.session: Any = None
        self.cb: Any = None
        self.sent: list[bytes] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def start_notify(self, _uuid, cb):
        self.cb = cb

    async def write_gatt_char(self, _uuid, data, response=False):
        assert not response
        plain = (self.session or self.base).decode(bytes(data))
        self.sent.append(plain)
        head = plain[:2]
        if head == b"\xe7\x01":
            return self.cb(None, self.base.encode(ble.frame(0xE7, 0x01, *self.seed)))
        if head == b"\xe7\x02":
            self.cb(None, self.base.encode(plain))
            self.session = ble.Codec(self.seed)
            return None
        if head == b"\xaa\x01":
            reply = ble.frame(0xAA, 0x01, int(self.on))
        elif head == b"\xaa\x04":
            reply = ble.frame(0xAA, 0x04, self.brightness)
        elif head == b"\xaa\x05":
            reply = ble.frame(0xAA, 0x05, 0x0D, 0xFF, 0, 0)
        else:
            if head == b"\x33\x01":
                self.on = bool(plain[2])
            elif head == b"\x33\x04":
                self.brightness, self.on = plain[2], True
            reply = ble.frame(0x33, plain[1], 0)
        return self.cb(None, self.session.encode(reply))


def run_on(bulb, cmd, *args, monkeypatch):
    import asyncio

    monkeypatch.setattr(ble, "BleakClient", lambda *_a, **_k: bulb)
    monkeypatch.setattr(ble, "DRAIN", 0)
    return asyncio.run(ble.run_link("GVH6008TEST", object(), cmd, list(args)))


def test_brightness_is_not_sent_to_an_off_bulb(monkeypatch, capsys):
    bulb = FakeBulb(on=False)
    assert run_on(bulb, "brightness", "25", monkeypatch=monkeypatch) == 0
    assert bulb.on is False
    assert not any(f[:2] == b"\x33\x04" for f in bulb.sent)
    assert "is off" in capsys.readouterr().err


def test_brightness_reaches_an_on_bulb(monkeypatch, capsys):
    bulb = FakeBulb(on=True)
    assert run_on(bulb, "brightness", "25", monkeypatch=monkeypatch) == 0
    assert bulb.brightness == 25
    assert "on   25%" in capsys.readouterr().out


def test_off_reaches_an_on_bulb(monkeypatch):
    bulb = FakeBulb(on=True)
    run_on(bulb, "off", monkeypatch=monkeypatch)
    assert bulb.on is False
