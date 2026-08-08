#!/usr/bin/env python3
"""Task 5, step 4 -- verification pass.

Re-submits every reference solution through the LIVE judge (real Docker
container, real comparator) and confirms Accepted across every hidden test.
Also runs the retained demonstration case (a submission that passes visible
samples but fails a hidden test) and confirms it does NOT come back Accepted.

Reference solutions are read from the database's reference_solution column
-- populated by scripts/generate_hidden_tests.py, which is the single source
of truth for this logic. This script does not carry its own copy.

Run from the repo root with the venv active and Docker running:
    python3 scripts/verify_task5.py

Requires, in order:
    python3 scripts/generate_hidden_tests.py   # writes seed_data.json
    python3 scripts/seed_problems.py           # loads it into Postgres
    python3 scripts/verify_task5.py            # this script
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Problem  # noqa: E402
from app.judge import judge  # noqa: E402

TARGET_SLUGS = [
    "two-sum", "valid-parentheses", "merge-intervals", "binary-search",
    "climbing-stairs", "3sum", "group-anagrams",
    "longest-substring-without-repeating-characters",
    "search-in-rotated-sorted-array", "product-of-array-except-self",
]

# The retained demonstration case: passes every visible sample, fails
# exactly one hidden test ('(' -- a single unclosed bracket). Real bug:
# never checks whether the stack is empty at the end, only that no
# mismatch happened during the scan. Kept here rather than in the DB
# because it's deliberately wrong and must never be mistaken for the real
# reference_solution.
DEMO_SLUG = "valid-parentheses"
DEMO_SOURCE = '''\
class Solution:
    def isValid(self, s: str) -> bool:
        pairs = {')': '(', ']': '[', '}': '{'}
        stack = []
        for ch in s:
            if ch in '([{':
                stack.append(ch)
            elif ch in pairs:
                if not stack or stack.pop() != pairs[ch]:
                    return False
        return True  # BUG: should be `return not stack`
'''


def main():
    with SessionLocal() as db:
        problems = {
            p.slug: p
            for p in db.scalars(select(Problem).where(Problem.slug.in_(TARGET_SLUGS)))
        }

        missing = set(TARGET_SLUGS) - set(problems)
        if missing:
            print(f"ERROR: not found in DB: {missing}")
            print("Run `python3 scripts/seed_problems.py` first.")
            sys.exit(1)

        no_ref = [s for s in TARGET_SLUGS if not problems[s].reference_solution]
        if no_ref:
            print(f"ERROR: reference_solution empty in DB for: {no_ref}")
            print("Run `python3 scripts/generate_hidden_tests.py` then "
                  "`python3 scripts/seed_problems.py` first.")
            sys.exit(1)

        print("=" * 78)
        print("STEP 4 -- REFERENCE SOLUTION VERIFICATION PASS")
        print("=" * 78)
        all_accepted = True
        for slug in TARGET_SLUGS:
            p = problems[slug]
            tests = p.hidden_tests or []
            if not tests:
                print(f"SKIP  {slug}: no hidden_tests in DB (re-seed first)")
                all_accepted = False
                continue
            result = judge(p, p.reference_solution, tests)
            verdict = result["verdict"]
            ok = verdict == "Accepted"
            all_accepted &= ok
            marker = "PASS" if ok else "FAIL"
            print(f"{marker}  {slug:<48} {verdict:<20} "
                  f"({len(tests)} hidden tests, {result.get('runtime_ms', '?')}ms)")
            if not ok:
                print(f"        failed_test_index={result.get('failed_test_index')}")
                print(f"        expected={result.get('expected_output')}")
                print(f"        actual={result.get('actual_output')}")

        print()
        print("=" * 78)
        print("DEMONSTRATION CASE -- must NOT be Accepted")
        print("=" * 78)
        demo_problem = problems[DEMO_SLUG]

        sample_result = judge(demo_problem, DEMO_SOURCE, demo_problem.sample_tests)
        print(f"vs sample_tests: {sample_result['verdict']} "
              f"(expected Accepted -- passes every visible sample)")

        hidden_result = judge(demo_problem, DEMO_SOURCE, demo_problem.hidden_tests)
        print(f"vs hidden_tests: {hidden_result['verdict']} "
              f"(expected Wrong Answer -- this is the point of the demo)")
        print(f"        failed_test_index={hidden_result.get('failed_test_index')}")
        print(f"        expected={hidden_result.get('expected_output')}")
        print(f"        actual={hidden_result.get('actual_output')}")

        demo_ok = (
            sample_result["verdict"] == "Accepted"
            and hidden_result["verdict"] != "Accepted"
        )

        print()
        print("=" * 78)
        if all_accepted and demo_ok:
            print("ALL CHECKS PASSED: every reference solution Accepted (read from "
                  "the DB's reference_solution column, not a hardcoded copy); "
                  "demonstration case correctly distinguishes submit from run.")
            sys.exit(0)
        else:
            print("*** SOME CHECKS FAILED, SEE ABOVE ***")
            sys.exit(1)


if __name__ == "__main__":
    main()
