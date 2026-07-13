import pytest

from corpus_tools.metrics import cer, strip_layout


def test_strip_layout_removes_all_whitespace():
    assert strip_layout("科学\n文艺 abc\t1") == "科学文艺abc1"


def test_cer_identical_is_zero():
    r = cer("科学文艺", "科学\n文艺")  # layout differences don't count
    assert r["cer"] == 0.0 and r["distance"] == 0 and r["ref_chars"] == 4


def test_cer_substitution():
    r = cer("科学文艺", "科字文艺")
    assert r == {"cer": 0.25, "distance": 1, "sub": 1, "dele": 0,
                 "ins": 0, "ref_chars": 4}


def test_cer_deletion_and_insertion():
    assert cer("科学文艺", "科文艺")["dele"] == 1      # hyp missing one ref char
    assert cer("科文艺", "科学文艺")["ins"] == 1       # hyp has one extra char


def test_cer_empty_hyp_is_one():
    r = cer("科学文艺", "")
    assert r["cer"] == 1.0 and r["dele"] == 4


def test_cer_empty_ref_raises():
    with pytest.raises(ValueError):
        cer("  \n ", "科学")


def test_cer_counts_sum_to_distance():
    r = cer("中国科学文艺一九七九", "中國科学芸一九七九年")
    assert r["sub"] + r["dele"] + r["ins"] == r["distance"]
