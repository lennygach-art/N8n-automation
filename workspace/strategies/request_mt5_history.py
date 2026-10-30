#!/usr/bin/env python3
"""Queue an MT5 M1-history export and wait for its JSON result."""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

QUEUE = Path(os.environ.get("MT5_QUEUE_DIR", "/data/workspace/mt5_queue"))
REQUESTS = QUEUE / "history_requests"
REPORTS = QUEUE / "history_reports"


def six_months_before(day: date) -> date:
    month_index = day.year * 12 + day.month - 1 - 6
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Request MT5 M1 bars as CSV")
    parser.add_argument("--symbol", default="XAUUSD", help="Exact broker symbol (default: XAUUSD)")
    parser.add_argument("--from", dest="start", help="Start date YYYY.MM.DD (default: six months ago)")
    parser.add_argument("--to", dest="end", help="End date YYYY.MM.DD (default: today UTC)")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("MT5_HISTORY_TIMEOUT_SEC", "300")))
    args = parser.parse_args()

    symbol = args.symbol.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", symbol):
        parser.error("symbol must be a plain MT5 symbol name")
    today = datetime.now(timezone.utc).date()
    start = args.start or six_months_before(today).strftime("%Y.%m.%d")
    end = args.end or today.strftime("%Y.%m.%d")
    try:
        start_day = datetime.strptime(start, "%Y.%m.%d").date()
        end_day = datetime.strptime(end, "%Y.%m.%d").date()
    except ValueError:
        parser.error("dates must use YYYY.MM.DD")
    if start_day > end_day:
        parser.error("--from must not be after --to")

    REQUESTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    run_id = "hist_" + uuid.uuid4().hex
    request = {"runId": run_id, "symbol": symbol, "from": start, "to": end}
    request_path = REQUESTS / f"{run_id}.json"
    temp_path = request_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(request), encoding="utf-8")
    os.replace(temp_path, request_path)
    print(json.dumps({"queued": True, **request}), file=sys.stderr, flush=True)

    deadline = time.monotonic() + args.timeout
    report_path = REPORTS / f"{run_id}.json"
    while time.monotonic() < deadline:
        if report_path.exists():
            result = json.loads(report_path.read_text(encoding="utf-8"))
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0 if result.get("ok") else 1
        time.sleep(1)

    print(json.dumps({"ok": False, "runId": run_id, "error": "timed out waiting for the MT5 history bridge"}), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
