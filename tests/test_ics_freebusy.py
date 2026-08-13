"""Tests for scheduler/ics_freebusy.py.

The privacy test is the load-bearing one: the cache contract is busy
intervals ONLY, so no event content (SUMMARY/DESCRIPTION/LOCATION) may
survive parsing in any form.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import load_script

fb = load_script("scheduler/ics_freebusy.py")

TZ = ZoneInfo("America/Chicago")


def make_ics(*events: str) -> str:
    body = "\n".join(events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{body}\nEND:VCALENDAR\n"


def vevent(*props: str) -> str:
    return "BEGIN:VEVENT\n" + "\n".join(props) + "\nEND:VEVENT"


def parse(ics: str, warnings: list[str] | None = None):
    return fb.parse_events(ics, TZ, warnings if warnings is not None else [])


class TestParsing:
    def test_simple_timed_event(self):
        events = parse(
            make_ics(
                vevent(
                    "DTSTART;TZID=America/Chicago:20260815T180000",
                    "DTEND;TZID=America/Chicago:20260815T200000",
                    "SUMMARY:Secret dinner",
                )
            )
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.start == datetime(2026, 8, 15, 18, 0, tzinfo=TZ)
        assert ev.end - ev.start == timedelta(hours=2)

    def test_utc_and_folded_lines(self):
        # 75-char folding: continuation lines start with a space.
        events = parse(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20260815T2\n 30000Z\n"
            "DTEND:20260816T000000Z\nEND:VEVENT\nEND:VCALENDAR\n"
        )
        assert len(events) == 1
        assert events[0].start.utcoffset() == timedelta(0)
        assert events[0].start.hour == 23

    def test_transparent_and_cancelled_excluded(self):
        events = parse(
            make_ics(
                vevent("DTSTART;VALUE=DATE:20260815", "TRANSP:TRANSPARENT"),
                vevent(
                    "DTSTART:20260815T180000Z",
                    "DTEND:20260815T190000Z",
                    "STATUS:CANCELLED",
                ),
            )
        )
        assert events == []

    def test_all_day_opaque_spans_full_day(self):
        events = parse(make_ics(vevent("DTSTART;VALUE=DATE:20260815", "TRANSP:OPAQUE")))
        assert len(events) == 1
        assert events[0].all_day
        assert events[0].end - events[0].start == timedelta(days=1)

    def test_duration_instead_of_dtend(self):
        events = parse(make_ics(vevent("DTSTART:20260815T180000Z", "DURATION:PT1H30M")))
        assert events[0].end - events[0].start == timedelta(hours=1, minutes=30)

    def test_no_content_properties_survive(self):
        """Privacy invariant: nothing derived from SUMMARY etc. is reachable."""
        events = parse(
            make_ics(
                vevent(
                    "DTSTART:20260815T180000Z",
                    "DTEND:20260815T190000Z",
                    "SUMMARY:Therapy with Dr. Private",
                    "LOCATION:123 Secret St",
                    "DESCRIPTION:Do not leak",
                )
            )
        )
        for ev in events:
            for value in vars(ev).values():
                assert "Private" not in str(value)
                assert "Secret" not in str(value)
                assert "leak" not in str(value)


class TestRecurrence:
    WIN_START = datetime(2026, 8, 10, tzinfo=TZ)
    WIN_END = datetime(2026, 9, 10, tzinfo=TZ)

    def expand_one(self, *props: str, warnings: list[str] | None = None):
        w = warnings if warnings is not None else []
        events = parse(make_ics(vevent(*props)), w)
        assert len(events) == 1
        return fb.expand(events[0], self.WIN_START, self.WIN_END, w)

    def test_weekly_byday_with_exdate(self):
        # Tue/Thu 6-7pm, skipping Tue Aug 18.
        occs = self.expand_one(
            "DTSTART;TZID=America/Chicago:20260811T180000",
            "DTEND;TZID=America/Chicago:20260811T190000",
            "RRULE:FREQ=WEEKLY;BYDAY=TU,TH",
            "EXDATE;TZID=America/Chicago:20260818T180000",
        )
        days = [(s.month, s.day) for s, _ in occs]
        assert (8, 11) in days and (8, 13) in days and (8, 20) in days
        assert (8, 18) not in days
        assert all(s.weekday() in (1, 3) for s, _ in occs)

    def test_count_terminates(self):
        occs = self.expand_one(
            "DTSTART:20260811T180000Z",
            "DTEND:20260811T190000Z",
            "RRULE:FREQ=DAILY;COUNT=3",
        )
        assert len(occs) == 3

    def test_until_terminates(self):
        occs = self.expand_one(
            "DTSTART:20260811T180000Z",
            "DTEND:20260811T190000Z",
            "RRULE:FREQ=DAILY;UNTIL=20260814T000000Z",
        )
        assert len(occs) == 3  # Aug 11, 12, 13

    def test_old_unbounded_weekly_fast_forwards_into_window(self):
        # Series started years ago; expansion must still land in the window.
        occs = self.expand_one(
            "DTSTART;TZID=America/Chicago:20200106T090000",
            "DTEND;TZID=America/Chicago:20200106T170000",
            "RRULE:FREQ=WEEKLY",
        )
        assert occs
        assert all(self.WIN_START <= s <= self.WIN_END for s, _ in occs)
        assert all(s.weekday() == 0 for s, _ in occs)

    def test_monthly(self):
        occs = self.expand_one(
            "DTSTART;TZID=America/Chicago:20260715T190000",
            "DTEND;TZID=America/Chicago:20260715T210000",
            "RRULE:FREQ=MONTHLY",
        )
        assert [(s.month, s.day) for s, _ in occs] == [(8, 15)]

    def test_unsupported_freq_warns_not_silent(self):
        warnings: list[str] = []
        self.expand_one(
            "DTSTART:20260811T180000Z",
            "DTEND:20260811T190000Z",
            "RRULE:FREQ=HOURLY",
            warnings=warnings,
        )
        assert warnings


class TestIntervals:
    def test_merge_overlapping(self):
        a = datetime(2026, 8, 15, 18, 0, tzinfo=TZ)
        ivs = [
            (a, a + timedelta(hours=2)),
            (a + timedelta(hours=1), a + timedelta(hours=3)),
            (a + timedelta(hours=5), a + timedelta(hours=6)),
        ]
        merged = fb.merge_intervals(ivs)
        assert len(merged) == 2
        assert merged[0] == (a, a + timedelta(hours=3))

    def test_clip_to_window(self):
        a = datetime(2026, 8, 15, tzinfo=TZ)
        clipped = fb.clip(
            [(a - timedelta(days=2), a + timedelta(days=2))], a, a + timedelta(days=1)
        )
        assert clipped == [(a, a + timedelta(days=1))]
