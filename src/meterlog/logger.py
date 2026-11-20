"""Meter readings: usage per interval and anomaly flags."""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import date


class MeterError(ValueError):
    pass


@dataclass(frozen=True)
class Reading:
    meter_id: str
    day: date
    value: float


@dataclass(frozen=True)
class Meter:
    meter_id: str
    type: str
    unit: str
    location: str
    rollover_at: float | None


@dataclass(frozen=True)
class Interval:
    meter_id: str
    start: date
    end: date
    usage: float
    days: int
    rollover: bool = False

    @property
    def per_day(self) -> float:
        return self.usage / self.days


@dataclass(frozen=True)
class Flag:
    meter_id: str
    day: date
    severity: str
    kind: str
    message: str


def load_readings(path: str) -> list[Reading]:
    out = []
    with open(path, newline="", encoding="utf-8") as handle:
        for n, row in enumerate(csv.DictReader(handle), start=2):
            where = f"{path} line {n}"
            try:
                day = date.fromisoformat((row.get("date") or "").strip())
            except ValueError as exc:
                raise MeterError(f"{where}: date must be YYYY-MM-DD") from exc
            try:
                value = float(row["reading"])
            except (KeyError, ValueError, TypeError) as exc:
                raise MeterError(f"{where}: reading must be a number") from exc
            meter_id = (row.get("meter_id") or "").strip()
            if not meter_id:
                raise MeterError(f"{where}: meter_id is empty")
            out.append(Reading(meter_id, day, value))
    return sorted(out, key=lambda r: (r.meter_id, r.day))


def load_meters(path: str) -> dict[str, Meter]:
    meters = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for n, row in enumerate(csv.DictReader(handle), start=2):
            roll = (row.get("rollover_at") or "").strip()
            try:
                limit = float(roll) if roll else None
            except ValueError as exc:
                raise MeterError(f"{path} line {n}: rollover_at must be a number") from exc
            m = Meter(row["meter_id"].strip(), row.get("type", "").strip(), row.get("unit", "").strip(),
                      row.get("location", "").strip(), limit)
            meters[m.meter_id] = m
    return meters


def group(readings: list[Reading]) -> dict[str, list[Reading]]:
    out: dict[str, list[Reading]] = {}
    for r in readings:
        out.setdefault(r.meter_id, []).append(r)
    return out


def analyse(readings: list[Reading], meters: dict[str, Meter] | None = None, spike_factor: float = 2.0,
            zero_days: int = 30, gap_days: int = 45) -> tuple[list[Interval], list[Flag]]:
    """Compute usage intervals and flag problems.

    A reading that is lower than the last good one is flagged and skipped (the next interval then
    spans both periods), unless the meter has a rollover limit that explains it.
    """
    meters = meters or {}
    intervals: list[Interval] = []
    flags: list[Flag] = []
    for meter_id, rows in group(readings).items():
        limit = meters[meter_id].rollover_at if meter_id in meters else None
        last: Reading | None = None
        history: list[float] = []
        for r in rows:
            if last is None:
                last = r
                continue
            if r.day == last.day:
                flags.append(Flag(meter_id, r.day, "error", "duplicate", f"second reading on {r.day}"))
                continue
            days = (r.day - last.day).days
            rolled = False
            usage = r.value - last.value
            if usage < 0:
                if limit and last.value > 0.5 * limit and r.value < 0.5 * limit:
                    usage, rolled = r.value + limit - last.value, True
                else:
                    flags.append(Flag(meter_id, r.day, "error", "decrease",
                                      f"reading {r.value:g} is below the previous {last.value:g}"))
                    continue
            if days > gap_days:
                flags.append(Flag(meter_id, r.day, "warning", "gap", f"{days} days since the previous reading"))
            interval = Interval(meter_id, last.day, r.day, usage, days, rolled)
            if usage == 0 and days >= zero_days:
                flags.append(Flag(meter_id, r.day, "warning", "no-usage", f"no consumption for {days} days"))
            elif len(history) >= 3 and usage > 0:
                base = statistics.median(history[-3:])
                if base > 0 and interval.per_day > spike_factor * base:
                    flags.append(Flag(meter_id, r.day, "warning", "spike",
                                      f"{interval.per_day:,.0f} per day is {interval.per_day / base:.1f}x the recent {base:,.0f}"))
            intervals.append(interval)
            if usage > 0:
                history.append(interval.per_day)
            last = r
    flags.sort(key=lambda f: (f.severity != "error", f.meter_id, f.day))
    return intervals, flags


def append_reading(path: str, meter_id: str, day: date, value: float) -> None:
    """Add one reading to the CSV after basic checks against the last reading of that meter."""
    existing = [r for r in load_readings(path) if r.meter_id == meter_id]
    if existing:
        last = existing[-1]
        if day <= last.day:
            raise MeterError(f"date {day} is not after the last reading on {last.day}")
        if value < last.value:
            raise MeterError(f"reading {value:g} is below the last reading {last.value:g}; check for a typo or a rollover")
    with open(path, "a", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerow([meter_id, day.isoformat(), f"{value:g}"])
