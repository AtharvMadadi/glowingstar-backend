"""Code execution and judging core.

User code is a LeetCode-style `class Solution` with a single method. A harness
wraps it, feeds each test case as positional arguments parsed from the stored
raw testcase strings, and emits results on a sentinel line so stray user prints
stay in stdout without corrupting the verdict.

Execution runs in a disposable Docker container with no network, capped memory,
capped PIDs, a read-only filesystem, and an unprivileged user. Wall-clock limit
is enforced inside the container via SIGALRM, with a subprocess timeout as a
backstop in case user code swallows the alarm.
"""

import ast
import json
import os
import subprocess
import time
import uuid

SENTINEL = "___GS_RESULT___"
TIME_LIMIT_S = 3
IMAGE = os.environ.get("JUDGE_IMAGE", "python:3.11-slim")
MEMORY = "256m"
PIDS = "64"
BACKSTOP_S = TIME_LIMIT_S + 12  # container start-up + teardown allowance

SUPPORTED = {"python3"}

HARNESS = '''
import json as _json, sys as _sys, time as _time, signal as _signal
from typing import *
from collections import *
import math, heapq, bisect, itertools, functools, re


class _GSTimeout(Exception):
    pass


def _gs_alarm(_signum, _frame):
    raise _GSTimeout()


_signal.signal(_signal.SIGALRM, _gs_alarm)

__USER_CODE__

def _gs_main():
    _payload = _json.loads(__PAYLOAD__)
    _sol = Solution()
    _fn = getattr(_sol, _payload["method"])
    _out = []
    _status = "ok"
    _signal.alarm(__LIMIT__)
    try:
        for _args in _payload["cases"]:
            _t0 = _time.perf_counter()
            _val = _fn(*_args)
            _out.append({"ok": True, "value": _val,
                         "ms": int((_time.perf_counter() - _t0) * 1000)})
    except _GSTimeout:
        _status = "timeout"
    except Exception as _e:
        _out.append({"ok": False, "error": type(_e).__name__ + ": " + str(_e)})
    finally:
        _signal.alarm(0)
    _sys.stdout.write("\\n__SENTINEL__" + _json.dumps(
        {"status": _status, "results": _out}, default=str))


_gs_main()
'''


class JudgeError(Exception):
    pass


def method_name(problem) -> str:
    """Derive the entry-point method from the stored Python template."""
    import re as _re

    tmpl = (problem.code_templates or {}).get("python3") or ""
    m = _re.search(r"def\s+(\w+)\s*\(\s*self", tmpl)
    if not m:
        raise JudgeError("no Python template available for this problem")
    return m.group(1)


def parse_args(raw_args: list[str]) -> list:
    out = []
    for a in raw_args:
        a = a.strip()
        try:
            out.append(ast.literal_eval(a))
        except (ValueError, SyntaxError):
            out.append(a.strip('"'))
    return out


def parse_expected(expected):
    if expected is None:
        return None
    s = str(expected).strip()
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        return s.strip('"')


def _key(x):
    return json.dumps(x, sort_keys=True, default=str)


def _canon(v, mode: str):
    if mode == "float":
        try:
            return round(float(v), 5)
        except (TypeError, ValueError):
            return v
    if mode == "unordered" and isinstance(v, list):
        return sorted(v, key=_key)
    if mode == "unordered_nested" and isinstance(v, list):
        inner = [sorted(x, key=_key) if isinstance(x, list) else x for x in v]
        return sorted(inner, key=_key)
    return v


def outputs_match(actual, expected, mode: str) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(actual) == bool(expected)
    return _canon(actual, mode) == _canon(expected, mode)


def run_in_docker(user_code: str, cases: list[list], method: str) -> dict:
    """Execute the harness in an isolated container.

    The program is piped to the container on stdin rather than bind-mounted,
    so the judge works identically whether the API runs on the host or inside
    a container talking to the host Docker daemon (where a container-local
    path would be meaningless).
    """
    payload = json.dumps({"method": method, "cases": cases})
    source = (
        HARNESS.replace("__USER_CODE__", user_code)
        .replace("__SENTINEL__", SENTINEL)
        .replace("__LIMIT__", str(TIME_LIMIT_S))
        .replace("__PAYLOAD__", json.dumps(payload))
    )

    container = f"gs-judge-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "--rm", "-i", "--name", container,
        "--network", "none",
        "--memory", MEMORY, "--memory-swap", MEMORY,
        "--cpus", "0.5", "--pids-limit", PIDS,
        "--read-only", "--tmpfs", "/tmp:size=16m,exec",
        "--user", "65534:65534",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "HOME=/tmp",
        IMAGE, "python", "-",
    ]

    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd, input=source, capture_output=True, text=True, timeout=BACKSTOP_S
        )
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr, rc = "", "", -1
        subprocess.run(["docker", "kill", container], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise JudgeError("docker CLI not found on PATH") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if not timed_out and rc == 125:
        raise JudgeError(f"container failed to start: {stderr.strip()[:300]}")

    payload_out = None
    if SENTINEL in stdout:
        stdout, _, tail = stdout.partition(SENTINEL)
        try:
            payload_out = json.loads(tail.strip())
        except json.JSONDecodeError:
            payload_out = None

    return {
        "stdout": stdout.rstrip("\n"),
        "stderr": stderr,
        "payload": payload_out,
        "exit_code": rc,
        "hard_timeout": timed_out,
        "elapsed_ms": elapsed_ms,
    }


def judge(problem, user_code: str, tests: list[dict]) -> dict:
    """Run user code against tests; return a verdict payload."""
    method = method_name(problem)
    mode = getattr(problem, "comparison", "exact") or "exact"

    cases = [parse_args(t["args_raw"]) for t in tests]
    ex = run_in_docker(user_code, cases, method)

    stderr = ex["stderr"] or ""
    payload = ex["payload"]

    if ex["hard_timeout"]:
        return _verdict("Time Limit Exceeded", ex,
                        detail=f"Exceeded {TIME_LIMIT_S}s limit")

    # No sentinel => the harness never completed.
    if payload is None:
        if "MemoryError" in stderr or ex["exit_code"] == 137:
            return _verdict("Runtime Error", ex, detail="Memory limit exceeded")
        if "SyntaxError" in stderr or "IndentationError" in stderr:
            return _verdict("Compile Error", ex, detail=stderr.strip()[-1500:])
        return _verdict("Runtime Error", ex,
                        detail=(stderr.strip() or "no output produced")[-1500:])

    if payload.get("status") == "timeout":
        return _verdict("Time Limit Exceeded", ex,
                        detail=f"Exceeded {TIME_LIMIT_S}s limit",
                        failed_index=len(payload.get("results") or []))

    results = payload.get("results") or []
    total_ms = 0
    for i, res in enumerate(results):
        if not res.get("ok"):
            return _verdict("Runtime Error", ex,
                            detail=res.get("error"), failed_index=i)

        total_ms += res.get("ms", 0)
        expected = parse_expected(tests[i].get("expected"))
        if not outputs_match(res.get("value"), expected, mode):
            return _verdict(
                "Wrong Answer", ex,
                failed_index=i,
                expected=json.dumps(expected, default=str),
                actual=json.dumps(res.get("value"), default=str),
            )

    if len(results) < len(tests):
        return _verdict("Runtime Error", ex,
                        detail="execution ended before all cases ran",
                        failed_index=len(results))

    out = _verdict("Accepted", ex)
    out["runtime_ms"] = total_ms
    return out


def _verdict(verdict, ex, detail=None, failed_index=None,
             expected=None, actual=None) -> dict:
    return {
        "verdict": verdict,
        "stdout": ex["stdout"],
        "stderr": detail if detail is not None else ex["stderr"],
        "runtime_ms": ex["elapsed_ms"],
        "failed_test_index": failed_index,
        "expected_output": expected,
        "actual_output": actual,
    }


def dry_run(problem, user_code: str, tests: list[dict], custom_input: str | None = None) -> dict:
    """Execute against sample or custom input, reporting per-case detail.

    Unlike judge(), this does not stop at the first failure and does not
    produce a verdict — it is the interactive 'Run' path.
    """
    method = method_name(problem)
    mode = getattr(problem, "comparison", "exact") or "exact"

    if custom_input:
        raw = [ln for ln in custom_input.split("\n")]
        cases = [parse_args(raw)]
        expectations = [None]
        displays = [custom_input]
    else:
        cases = [parse_args(t["args_raw"]) for t in tests]
        expectations = [t.get("expected") for t in tests]
        displays = [t.get("display_input") for t in tests]

    ex = run_in_docker(user_code, cases, method)
    payload = ex["payload"]
    stderr = ex["stderr"] or ""

    if ex["hard_timeout"] or (payload or {}).get("status") == "timeout":
        return {
            "status": "Time Limit Exceeded",
            "stdout": ex["stdout"],
            "stderr": f"Exceeded {TIME_LIMIT_S}s limit",
            "runtime_ms": ex["elapsed_ms"],
            "results": [],
        }

    if payload is None:
        kind = (
            "Compile Error"
            if ("SyntaxError" in stderr or "IndentationError" in stderr)
            else "Runtime Error"
        )
        return {
            "status": kind,
            "stdout": ex["stdout"],
            "stderr": (stderr.strip() or "no output produced")[-1500:],
            "runtime_ms": ex["elapsed_ms"],
            "results": [],
        }

    results = []
    for i, res in enumerate(payload.get("results") or []):
        if not res.get("ok"):
            results.append({
                "index": i,
                "input": displays[i] if i < len(displays) else None,
                "expected": expectations[i] if i < len(expectations) else None,
                "actual": None,
                "passed": False,
                "runtime_ms": None,
                "error": res.get("error"),
            })
            continue

        actual = res.get("value")
        exp_raw = expectations[i] if i < len(expectations) else None
        passed = None
        if exp_raw is not None:
            passed = outputs_match(actual, parse_expected(exp_raw), mode)

        results.append({
            "index": i,
            "input": displays[i] if i < len(displays) else None,
            "expected": exp_raw,
            "actual": json.dumps(actual, default=str),
            "passed": passed,
            "runtime_ms": res.get("ms"),
            "error": None,
        })

    return {
        "status": "Finished",
        "stdout": ex["stdout"],
        "stderr": stderr,
        "runtime_ms": sum(r["runtime_ms"] or 0 for r in results),
        "results": results,
    }
