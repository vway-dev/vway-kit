"""구간 연산·시간 형식 — 여러 세션의 구간을 한 번만 세는가, 상한을 어떻게 자르는가."""

from datetime import UTC, datetime, timedelta

from scripts.worklog import IDLE, capped, hhmm, intersect, merge, subtract, total

T0 = datetime(2026, 1, 7, 5, 0, tzinfo=UTC)


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_merge_joins_overlap_and_touching_spans():
    assert merge([(m(10), m(20)), (m(0), m(5)), (m(5), m(8)), (m(15), m(30))]) == [
        (m(0), m(8)),
        (m(10), m(30)),
    ]


def test_merge_drops_empty_and_inverted_spans():
    assert merge([(m(5), m(5)), (m(9), m(3))]) == []


def test_intersect_keeps_only_common_time():
    assert intersect([(m(0), m(10)), (m(20), m(30))], [(m(5), m(25))]) == [
        (m(5), m(10)),
        (m(20), m(25)),
    ]


def test_subtract_cuts_holes():
    assert subtract([(m(0), m(30))], [(m(5), m(10)), (m(20), m(40))]) == [
        (m(0), m(5)),
        (m(10), m(20)),
    ]


def test_capped_cuts_at_fifteen_minutes():
    assert IDLE == timedelta(minutes=15)
    assert capped((m(0), m(16))) == (m(0), m(15))
    assert capped((m(0), m(15))) == (m(0), m(15))
    assert capped((m(0), m(3))) == (m(0), m(3))


def test_total_counts_overlap_once():
    assert total([(m(0), m(10)), (m(5), m(15))]) == timedelta(minutes=15)


def test_hhmm_floors_minutes_and_passes_24_hours():
    assert hhmm(timedelta(minutes=83, seconds=59)) == "01:23"
    assert hhmm(timedelta(hours=29, minutes=10)) == "29:10"
    assert hhmm(timedelta(0)) == "00:00"
