"""IANA timezone normalization for EventKit and other external sources."""

from common.timezones import normalize_timezone


def test_normalize_keeps_valid_iana():
    assert normalize_timezone("Asia/Shanghai") == "Asia/Shanghai"
    assert normalize_timezone("UTC") == "UTC"


def test_normalize_maps_common_aliases_and_fixed_offsets():
    assert normalize_timezone("Asia/Beijing") == "Asia/Shanghai"
    assert normalize_timezone("GMT+0800") == "Etc/GMT-8"
    assert normalize_timezone("GMT+08:00") == "Etc/GMT-8"
    assert normalize_timezone("GMT-5") == "Etc/GMT+5"


def test_normalize_falls_back_for_unknown_labels():
    assert normalize_timezone("CST") == "UTC"
    assert normalize_timezone("") == "UTC"
    assert normalize_timezone(None) == "UTC"
