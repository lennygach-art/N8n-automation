#!/usr/bin/env python3
"""n8n side of the MT5 backtest queue.

Called by the n8n "Execute Command" node with one JSON argument (one backtest run).
It drops a request file into the shared queue folder, waits for the MT5 watcher
to write back the Strategy Tester report, and prints the report to stdout.
If anything goes wrong it prints NO_REPORT (and the reason to stderr) and exits 0,
so one bad run never stops the whole campaign.

Environment variables (all optional):
  MT5_QUEUE_DIR         shared queue folder        (default /data/workspace/mt5_queue)
  BACKTEST_TIMEOUT_SEC  max wait for one report    (default 3600)
"""
import json
import os
import sys
import time

QUEUE = os.environ.get("MT5_QUEUE_DIR", "/data/workspace/mt5_queue")
REQ_DIR = os.path.join(QUEUE, "requests")
REP_DIR = os.path.join(QUEUE, "reports")
HEARTBEAT = os.path.join(QUEUE, "watcher_alive.txt")
HEARTBEAT_MAX_AGE = 120  # seconds without a heartbeat = watcher is not running
TIMEOUT = int(os.environ.get("BACKTEST_TIMEOUT_SEC", "3600"))
POLL = 5


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def no_report(reason):
    log("NO_REPORT: " + reason)
    print("NO_REPORT")
    return 0


def watcher_age():
    try:
        return time.time() - os.path.getmtime(HEARTBEAT)
    except OSError:
        return float("inf")


def read_report(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:200]:
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        return no_report("no JSON argument given")
    try:
        req = json.loads(sys.argv[1])
        run_id = str(req["runId"])
    except (ValueError, KeyError) as exc:
        return no_report("bad request JSON: %s" % exc)

    os.makedirs(REQ_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    age = watcher_age()
    if age > HEARTBEAT_MAX_AGE:
        return no_report("MT5 watcher is not running (no heartbeat for %ds)" % min(age, 999999))

    report_paths = [os.path.join(REP_DIR, run_id + ext) for ext in (".htm", ".html")]
    err_path = os.path.join(REP_DIR, run_id + ".err")
    for stale in report_paths + [err_path]:
        if os.path.exists(stale):
            os.remove(stale)

    tmp = os.path.join(REQ_DIR, run_id + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(req, f)
    os.replace(tmp, os.path.join(REQ_DIR, run_id + ".json"))
    log("queued " + run_id)

    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if os.path.exists(err_path):
            with open(err_path, encoding="utf-8", errors="replace") as f:
                reason = f.read().strip()
            return no_report("watcher reported: " + reason)
        for p in report_paths:
            if os.path.exists(p):
                size = os.path.getsize(p)
                time.sleep(2)  # make sure the file is fully written
                if size > 0 and os.path.getsize(p) == size:
                    print(read_report(p))
                    return 0
        if watcher_age() > HEARTBEAT_MAX_AGE:
            return no_report("MT5 watcher stopped while waiting")
        time.sleep(POLL)
    return no_report("timed out after %ds waiting for the report" % TIMEOUT)


if __name__ == "__main__":
    sys.exit(main())
