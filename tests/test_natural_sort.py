from __future__ import annotations

from vlm.core.playlist import natural_key


def test_numbers_sort_numerically() -> None:
    names = ["Show 10.mkv", "Show 2.mkv", "show 1.mkv", "Show 02.mkv"]
    assert sorted(names, key=natural_key) == [
        "show 1.mkv",
        "Show 2.mkv",
        "Show 02.mkv",
        "Show 10.mkv",
    ]


def test_suffixes_after_numbers() -> None:
    names = ["Ep 10b", "Ep 9a", "Ep 10", "Ep 9"]
    assert sorted(names, key=natural_key) == ["Ep 9", "Ep 9a", "Ep 10", "Ep 10b"]


def test_case_insensitive() -> None:
    assert natural_key("ABC 1") == natural_key("abc 1")


def test_padding_sorts_identically() -> None:
    assert sorted(["Ep 07", "Ep 10", "Ep 7"], key=natural_key) == ["Ep 07", "Ep 7", "Ep 10"]
