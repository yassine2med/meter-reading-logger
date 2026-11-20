import shutil
from datetime import date
from pathlib import Path

import pytest

from meterlog.__main__ import main
from meterlog.logger import (Meter, MeterError, Reading, analyse, append_reading, load_meters, load_readings)

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def result():
    return analyse(load_readings(str(EX / "readings.csv")), load_meters(str(EX / "meters.csv")))


def r(meter, day, value):
    return Reading(meter, date.fromisoformat(day), value)


def kinds(flags, meter=None):
    return {(f.meter_id, f.kind) for f in flags if meter is None or f.meter_id == meter}


def test_loads_all_readings():
    assert len(load_readings(str(EX / "readings.csv"))) == 30


def test_usage_difference_and_days(result):
    intervals, _ = result
    first = next(i for i in intervals if i.meter_id == "E-MAIN")
    assert (first.usage, first.days) == (29400, 30)


def test_rollover_is_not_a_decrease(result):
    intervals, flags = result
    wrap = next(i for i in intervals if i.meter_id == "W-MAIN" and i.rollover)
    assert wrap.usage == 12600
    assert ("W-MAIN", "decrease") not in kinds(flags)


def test_decrease_flagged_as_error(result):
    _, flags = result
    assert ("G-BOILER", "decrease") in kinds(flags)
    assert next(f for f in flags if f.kind == "decrease").severity == "error"


def test_errors_sorted_before_warnings(result):
    assert result[1][0].severity == "error"


def test_decreased_reading_is_skipped_as_baseline(result):
    intervals, _ = result
    last = [i for i in intervals if i.meter_id == "G-BOILER"][-1]
    assert (last.start, last.end) == (date(2026, 9, 1), date(2026, 11, 1))


def test_spike_flagged(result):
    assert ("E-MAIN", "spike") in kinds(result[1])


def test_zero_usage_flagged(result):
    assert sum(1 for f in result[1] if f.kind == "no-usage") == 2


def test_gap_flagged(result):
    assert ("W-MAIN", "gap") in kinds(result[1])


def test_normal_meter_has_no_flags():
    rows = [r("A", f"2026-0{m}-01", 1000 * m) for m in range(1, 8)]
    assert analyse(rows)[1] == []


def test_duplicate_date_flagged():
    flags = analyse([r("A", "2026-01-01", 1), r("A", "2026-01-01", 2), r("A", "2026-02-01", 50)])[1]
    assert ("A", "duplicate") in kinds(flags)


def test_without_rollover_limit_a_wrap_is_a_decrease():
    flags = analyse([r("A", "2026-01-01", 99000), r("A", "2026-02-01", 500)])[1]
    assert ("A", "decrease") in kinds(flags)


def test_rollover_needs_plausible_values():
    meters = {"A": Meter("A", "water", "gal", "x", 100000)}
    flags = analyse([r("A", "2026-01-01", 20000), r("A", "2026-02-01", 100)], meters)[1]
    assert ("A", "decrease") in kinds(flags)


def test_spike_factor_is_adjustable():
    rows = [r("A", "2026-01-01", 0), r("A", "2026-02-01", 100), r("A", "2026-03-01", 200),
            r("A", "2026-04-01", 300), r("A", "2026-05-01", 450)]
    assert analyse(rows, spike_factor=2.0)[1] == []
    assert ("A", "spike") in kinds(analyse(rows, spike_factor=1.3)[1])


def test_append_reading_checks(tmp_path):
    f = tmp_path / "r.csv"
    shutil.copy(EX / "readings.csv", f)
    append_reading(str(f), "E-MAIN", date(2026, 12, 1), 785000)
    assert any(x.day == date(2026, 12, 1) for x in load_readings(str(f)))
    with pytest.raises(MeterError):
        append_reading(str(f), "E-MAIN", date(2026, 11, 15), 790000)
    with pytest.raises(MeterError):
        append_reading(str(f), "E-MAIN", date(2026, 12, 15), 100)


def test_bad_file_values(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("meter_id,date,reading\nA,2026-01-01,abc\n")
    with pytest.raises(MeterError):
        load_readings(str(f))
    f.write_text("meter_id,date,reading\nA,01/01/2026,5\n")
    with pytest.raises(MeterError):
        load_readings(str(f))


def test_cli_codes(tmp_path):
    reads, meters = str(EX / "readings.csv"), str(EX / "meters.csv")
    assert main(["flags", reads, "--meters", meters]) == 1
    assert main(["flags", reads, "--meters", meters, "--spike", "10", "--zero-days", "99", "--gap-days", "999"]) == 1
    assert main(["usage", reads, "--meters", meters, "--meter", "E-MAIN"]) == 0
    assert main(["flags", str(tmp_path / "none.csv")]) == 2
    copy = tmp_path / "r.csv"
    shutil.copy(EX / "readings.csv", copy)
    assert main(["add", str(copy), "E-MAIN", "2026-12-01", "790000"]) == 0
    assert main(["add", str(copy), "E-MAIN", "2026-12-02", "5"]) == 2
