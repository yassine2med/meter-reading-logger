"""Command line entry: python -m meterlog usage|flags|add."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .logger import MeterError, analyse, append_reading, load_meters, load_readings


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 1 when flags are found, 2 on bad input."""
    parser = argparse.ArgumentParser(prog="meterlog", description="Meter reading log with anomaly flags")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("usage", "consumption for each reading interval"), ("flags", "list anomalies")):
        p = sub.add_parser(name, help=text)
        p.add_argument("readings")
        p.add_argument("--meters", help="meters CSV with units and rollover limits")
        p.add_argument("--spike", type=float, default=2.0, help="flag a rate above this multiple of the recent median (default 2)")
        p.add_argument("--zero-days", type=int, default=30, help="flag zero use over at least this many days (default 30)")
        p.add_argument("--gap-days", type=int, default=45, help="flag a gap longer than this (default 45)")
        if name == "usage":
            p.add_argument("--meter", help="only this meter")
    a = sub.add_parser("add", help="append one reading after checking it")
    a.add_argument("readings")
    a.add_argument("meter_id")
    a.add_argument("date")
    a.add_argument("reading", type=float)
    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            append_reading(args.readings, args.meter_id, date.fromisoformat(args.date), args.reading)
            print(f"added {args.meter_id} {args.date} {args.reading:g}")
            return 0
        meters = load_meters(args.meters) if args.meters else {}
        intervals, flags = analyse(load_readings(args.readings), meters, args.spike, args.zero_days, args.gap_days)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr)
        return 2
    except (MeterError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.command == "usage":
        print(f"{'meter':<11}{'from':<12}{'to':<12}{'days':>5}{'usage':>10}{'per day':>10}  unit")
        for i in intervals:
            if args.meter and i.meter_id != args.meter:
                continue
            unit = meters[i.meter_id].unit if i.meter_id in meters else ""
            note = "  rollover" if i.rollover else ""
            print(f"{i.meter_id:<11}{i.start.isoformat():<12}{i.end.isoformat():<12}{i.days:>5}{i.usage:>10,.0f}{i.per_day:>10,.1f}  {unit}{note}")
        return 0
    for f in flags:
        print(f"{f.severity.upper():7} {f.meter_id:<10}{f.day}  {f.kind}: {f.message}")
    print(f"{len(flags)} flag(s)")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
