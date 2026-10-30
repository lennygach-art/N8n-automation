#!/usr/bin/env python3
"""MT5 side of the backtest queue. Run this INSIDE the mt5-forwardtest container.

Watches <queue>/requests for *.json files written by run_single_backtest.py,
runs the MT5 Strategy Tester headlessly for each one (in a separate portable copy
of MT5, so your live/forward-test terminal is not touched), and copies the HTML
report to <queue>/reports.

  python3 mt5_watcher.py --check    show detected paths and exit (run this first)
  python3 mt5_watcher.py            start watching

Paths are guesses for the gmag11/metatrader5_vnc image. Override with env vars:
  MT5_QUEUE_DIR, MT5_DIR, MT5_TESTER_DIR, WINEPREFIX, DISPLAY, RUN_TIMEOUT_SEC
Everything is logged to <queue>/watcher.log.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

QUEUE = os.environ.get("MT5_QUEUE_DIR", "/data/workspace/mt5_queue")
REQ_DIR = os.path.join(QUEUE, "requests")
REP_DIR = os.path.join(QUEUE, "reports")
DONE_DIR = os.path.join(QUEUE, "done")
HEARTBEAT = os.path.join(QUEUE, "watcher_alive.txt")
LOG_FILE = os.path.join(QUEUE, "watcher.log")

WINEPREFIX = os.environ.get("WINEPREFIX", "/config/.wine")
MT5_DIR = os.environ.get("MT5_DIR", os.path.join(WINEPREFIX, "drive_c", "Program Files", "MetaTrader 5"))
TESTER_DIR = os.environ.get("MT5_TESTER_DIR", "/config/mt5_tester")  # portable copy used for tests
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT_SEC", "3600"))


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def beat():
    with open(HEARTBEAT, "w") as f:
        f.write(str(time.time()))


def win_path(path):
    return "Z:" + path.replace("/", "\\")


def tester_ini(req):
    lines = [
        "[Tester]",
        "Expert=%s" % req["expert"],
        "Symbol=%s" % req["symbol"],
        "Period=%s" % req["period"],
        "Model=%s" % req.get("model", 4),
        "ExecutionMode=0",
        "Optimization=0",
        "FromDate=%s" % req["from"],
        "ToDate=%s" % req["to"],
        "ForwardMode=0",
        "Deposit=%s" % req.get("deposit", 1000),
        "Currency=%s" % req.get("currency", "USD"),
        "Leverage=%s" % req.get("leverage", 100),
        "Report=%s" % req["runId"],
        "ReplaceReport=1",
        "ShutdownTerminal=1",
        "Visual=0",
        "",
        "[TesterInputs]",
    ]
    for key, value in (req.get("params") or {}).items():
        lines.append("%s=%s" % (key, value))
    return "\r\n".join(lines) + "\r\n"


def experts_source():
    """Where the compiled .ex5 files live in the live MT5 install."""
    candidates = [os.path.join(MT5_DIR, "MQL5", "Experts")]
    candidates += glob.glob(os.path.join(
        WINEPREFIX, "drive_c", "users", "*", "AppData", "Roaming", "MetaQuotes", "Terminal", "*", "MQL5", "Experts"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def prepare_tester():
    if not os.path.exists(os.path.join(TESTER_DIR, "terminal64.exe")):
        if not os.path.exists(os.path.join(MT5_DIR, "terminal64.exe")):
            raise RuntimeError("MT5 not found at %s (set MT5_DIR)" % MT5_DIR)
        log("creating portable test copy in %s (first run only, can take a while)" % TESTER_DIR)
        shutil.copytree(MT5_DIR, TESTER_DIR)
    src = experts_source()
    if src is None:
        raise RuntimeError("could not find an MQL5/Experts folder to copy your EA from")
    shutil.copytree(src, os.path.join(TESTER_DIR, "MQL5", "Experts"), dirs_exist_ok=True)


def find_report(run_id, since):
    hits = []
    for root, _dirs, files in os.walk(TESTER_DIR):
        for name in files:
            if name.startswith(run_id) and name.lower().endswith((".htm", ".html")):
                path = os.path.join(root, name)
                if os.path.getmtime(path) >= since - 5:
                    hits.append(path)
    return max(hits, key=os.path.getmtime) if hits else None


def run_one(req_path):
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    run_id = str(req["runId"])
    log("running " + run_id)
    err_path = os.path.join(REP_DIR, run_id + ".err")
    try:
        prepare_tester()
        ini = os.path.join(TESTER_DIR, run_id + ".ini")
        with open(ini, "w", encoding="utf-8", newline="") as f:
            f.write(tester_ini(req))
        env = dict(os.environ)
        env.setdefault("WINEPREFIX", WINEPREFIX)
        env.setdefault("DISPLAY", ":1")
        started = time.time()
        proc = subprocess.Popen(
            ["wine", os.path.join(TESTER_DIR, "terminal64.exe"), "/portable", "/config:" + win_path(ini)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while proc.poll() is None:
            beat()
            if time.time() - started > RUN_TIMEOUT:
                proc.kill()
                raise RuntimeError("tester exceeded %ds and was stopped" % RUN_TIMEOUT)
            time.sleep(5)
        report = find_report(run_id, started)
        if report is None:
            raise RuntimeError("tester finished but no report named %s was found under %s" % (run_id, TESTER_DIR))
        shutil.copyfile(report, os.path.join(REP_DIR, run_id + ".htm"))
        log("done " + run_id)
    except Exception as exc:  # noqa: BLE001 - report every failure back to n8n
        log("FAILED %s: %s" % (run_id, exc))
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(str(exc))
    finally:
        shutil.move(req_path, os.path.join(DONE_DIR, os.path.basename(req_path)))


def check():
    print("queue dir      :", QUEUE, "(exists)" if os.path.isdir(QUEUE) else "(MISSING)")
    print("wine           :", shutil.which("wine") or "NOT FOUND")
    print("wineprefix     :", WINEPREFIX, "(exists)" if os.path.isdir(WINEPREFIX) else "(MISSING)")
    print("MT5 install    :", MT5_DIR, "(found)" if os.path.exists(os.path.join(MT5_DIR, "terminal64.exe")) else "(terminal64.exe NOT FOUND)")
    print("EA folder      :", experts_source() or "NOT FOUND")
    print("tester copy    :", TESTER_DIR, "(exists)" if os.path.exists(os.path.join(TESTER_DIR, "terminal64.exe")) else "(will be created on first run)")
    print("DISPLAY        :", os.environ.get("DISPLAY", "(not set, will use :1)"))


def main():
    if "--check" in sys.argv:
        check()
        return
    for d in (REQ_DIR, REP_DIR, DONE_DIR):
        os.makedirs(d, exist_ok=True)
    log("watcher started, queue=" + QUEUE)
    while True:
        beat()
        for req_path in sorted(glob.glob(os.path.join(REQ_DIR, "*.json"))):
            run_one(req_path)
        time.sleep(3)


if __name__ == "__main__":
    main()
