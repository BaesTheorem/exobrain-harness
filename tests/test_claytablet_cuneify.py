"""Characterization tests for cuneify: ATF readings to Unicode cuneiform through a sign list.

The sign list here is a six-sign extract in the Oracc .asl format, so the tests need no download.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "claytablet" / "lib"))

import cuneify  # noqa: E402

ASL = """@sign A
@ucun\t𒀀
@v\ta
@end sign

@sign NA
@ucun\t𒈾
@v\tna
@end sign

@sign ZE₂
@ucun\t𒍢
@v\tṣi
@v\tze₂
@end sign

@sign ZI
@ucun\t𒍣
@v\tṣi₂
@v\tzi
@form ZI@g
@ucun\t𒍤
@v\tzi
@end sign

@sign AN
@ucun\t𒀭
@v\tan
@v-\tna
@end sign

@sign U
@ucun\t𒌋
@v\tu
@end sign
"""


@pytest.fixture
def signs(tmp_path):
    p = tmp_path / "mini.asl"
    p.write_text(ASL, encoding="utf-8")
    return cuneify.load_osl(str(p))


def test_index_picks_the_sign(signs):
    val2sign, name2ucun = signs
    unknown = []
    cun, names = cuneify.cuneify_line("1. a-na s,i s,i2", val2sign, name2ucun, unknown)
    assert cun == "𒀀𒈾 𒍢 𒍣"
    assert names == ["A", "NA", "ZE₂", "ZI"]
    assert unknown == []


def test_variant_form_and_deprecated_reading_do_not_win(signs):
    val2sign, _ = signs
    assert val2sign["zi"][0] == "ZI"       # the @form block does not take the parent's reading
    assert val2sign["na"][0] == "NA"       # a "@v-" reading on AN is ignored


def test_determinative_and_damage_marks(signs):
    val2sign, name2ucun = signs
    unknown = []
    cun, names = cuneify.cuneify_line("7. {d}na# [a]-na x", val2sign, name2ucun, unknown)
    assert cun == "𒀭𒈾 𒀀𒈾"
    assert names == ["AN", "NA", "A", "NA"]


def test_unknown_reading_is_reported(signs):
    val2sign, name2ucun = signs
    unknown = []
    cuneify.cuneify_line("a-qux", val2sign, name2ucun, unknown)
    assert unknown == ["qux"]
