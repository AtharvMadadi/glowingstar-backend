#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import SessionLocal
from app.judge import judge
from app.models import Problem

CORRECT = """
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, n in enumerate(nums):
            if target - n in seen:
                return [seen[target - n], i]
            seen[n] = i
"""

REVERSED_ORDER = """
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, n in enumerate(nums):
            if target - n in seen:
                return [i, seen[target - n]]
            seen[n] = i
"""

WRONG = """
class Solution:
    def twoSum(self, nums, target):
        return [0, 0]
"""

CRASH = """
class Solution:
    def twoSum(self, nums, target):
        return nums[999]
"""

SYNTAX = """
class Solution:
    def twoSum(self, nums, target)
        return []
"""

SLOW = """
class Solution:
    def twoSum(self, nums, target):
        x = 0
        for i in range(10**9):
            x += i
        return [0, 1]
"""

CASES = [
    ("correct", CORRECT, "Accepted"),
    ("reversed order (tests unordered mode)", REVERSED_ORDER, "Accepted"),
    ("wrong answer", WRONG, "Wrong Answer"),
    ("runtime error", CRASH, "Runtime Error"),
    ("syntax error", SYNTAX, "Compile Error"),
    ("infinite loop", SLOW, "Time Limit Exceeded"),
]

with SessionLocal() as db:
    p = db.scalar(select(Problem).where(Problem.slug == "two-sum"))
    print(f"problem: {p.title}  comparison={p.comparison}  tests={len(p.sample_tests)}\n")
    for label, code, expected in CASES:
        r = judge(p, code, p.sample_tests)
        got = r["verdict"]
        mark = "PASS" if got == expected else "FAIL"
        print(f"[{mark}] {label:38s} -> {got}")
        if got != expected:
            print(f"        expected {expected}")
            print(f"        stderr: {(r['stderr'] or '')[:200]}")
        if got == "Wrong Answer":
            print(f"        case {r['failed_test_index']}: "
                  f"expected {r['expected_output']} got {r['actual_output']}")
