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
