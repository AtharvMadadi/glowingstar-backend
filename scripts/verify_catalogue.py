#!/usr/bin/env python3
"""Catalogue verification gate.

One command that answers a single question: does this catalogue still judge
correctly? It runs two independent passes over every seeded problem.

  DATA        Structural checks that need no Docker and no execution --
              statement/constraints/examples populated, at least one visible
              test, input and expected-output counts paired, and a comparison
              mode consistent with the shape of the expected output.

  EXECUTION   Loads each problem's stored reference_solution and runs it
              through the live judge (real Docker container, real comparator)
              against its hidden tests, falling back to sample tests where no
              hidden tests exist. A reference solution that does not come back
              Accepted means the catalogue, the judge, or the comparator has
              regressed.

Exits non-zero if anything FAILS, so it can gate a commit, a CI job, or a
deploy rather than requiring a person to read output.

Two design decisions, both stated in the handover:

  1. Problems with no reference_solution are SKIPPED, not failed. 10 of 50
     have one; failing on the other 40 would make the gate red from the first
     run and it would be ignored within a day. Skips are counted and reported
     as a coverage number instead. Use --fail-on-skip to make coverage
     mandatory once the set is complete.

  2. Subset runs are supported (--slug, --difficulty, --data-only). The
     execution pass costs roughly a second of container start-up per problem,
     so a full run is slow enough that nobody would run it while iterating.
     --data-only takes under a second and catches most authoring mistakes.
     Note that --data-only still needs the database (that is where the
     catalogue lives); what it skips is launching a judge container per
     problem.

Usage
-----
    python3 scripts/verify_catalogue.py                  # full gate
    python3 scripts/verify_catalogue.py --data-only      # no Docker, seconds
    python3 scripts/verify_catalogue.py --slug two-sum --slug 3sum
    python3 scripts/verify_catalogue.py --difficulty Easy
    python3 scripts/verify_catalogue.py --fail-on-skip   # coverage mandatory

Requires the database to be up and seeded:
    docker compose up -d db
    alembic upgrade head
    python3 scripts/seed_problems.py
"""

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Problem  # noqa: E402
from app.judge import judge, method_name, parse_expected, JudgeError  # noqa: E402

VALID_MODES = {"exact", "unordered", "unordered_nested", "float"}
LINE = "=" * 78
RULE = "-" * 78


# --------------------------------------------------------------------------
# data validation
# --------------------------------------------------------------------------

def _shape_of(expected):
    """Classify a stored expected-output string. Returns one of:
    'list_of_lists', 'list', 'number', 'other'."""
    val = parse_expected(expected)
    if isinstance(val, list):
        if val and all(isinstance(x, list) for x in val):
            return "list_of_lists"
        return "list"
    if isinstance(val, bool):
        return "other"
    if isinstance(val, (int, float)):
        return "number"
    return "other"


def _check_tests(tests, label, problems_out):
    """Structural checks on one test array. Appends messages to problems_out."""
    for i, t in enumerate(tests):
        if not isinstance(t, dict):
            problems_out.append(f"{label}[{i}]: not an object")
            continue
        args = t.get("args_raw")
        if args is None:
            problems_out.append(f"{label}[{i}]: no args_raw (input missing)")
        elif not isinstance(args, list) or not args:
            problems_out.append(f"{label}[{i}]: args_raw is empty or not a list")
        if "expected" not in t or t["expected"] is None:
            problems_out.append(f"{label}[{i}]: no expected output")


def validate_data(p):
    """Return (errors, warnings) for one problem. Errors fail the gate."""
    errors, warnings = [], []

    if not (p.description or "").strip():
        errors.append("statement is empty")
    if not (p.constraints or "").strip():
        errors.append("constraints are empty")
    if not p.tags:
        warnings.append("no tags -- will not surface under any filter")

    samples = p.sample_tests or []
    hidden = p.hidden_tests or []

    if not samples:
        errors.append("no visible test cases (examples not populated)")
    _check_tests(samples, "sample_tests", errors)
    _check_tests(hidden, "hidden_tests", errors)

    mode = (p.comparison or "").strip()
    if mode not in VALID_MODES:
        errors.append(f"comparison mode {mode!r} is not one of {sorted(VALID_MODES)}")
    elif samples:
        shapes = {_shape_of(t.get("expected")) for t in samples if isinstance(t, dict)}
        if mode == "unordered_nested" and "list_of_lists" not in shapes:
            errors.append(
                "comparison=unordered_nested but no sample expects a list of lists "
                f"(shapes seen: {sorted(shapes)}) -- inner sort will never apply"
            )
        if mode == "unordered" and not shapes & {"list", "list_of_lists"}:
            errors.append(
                "comparison=unordered but no sample expects a list "
                f"(shapes seen: {sorted(shapes)}) -- sort will never apply"
            )
        if mode == "float" and "number" not in shapes:
            errors.append(
                "comparison=float but no sample expects a number "
                f"(shapes seen: {sorted(shapes)})"
            )
        if mode == "exact" and shapes == {"list_of_lists"}:
            warnings.append(
                "comparison=exact with list-of-lists output -- confirm order is "
                "actually significant, or a correct solution will be rejected"
            )

    try:
        method_name(p)
    except JudgeError as exc:
        errors.append(f"entry point cannot be derived: {exc}")

    return errors, warnings


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_cli():
    ap = argparse.ArgumentParser(
        description="Verify every seeded problem: data integrity plus a live "
                    "judge run of its reference solution."
    )
    ap.add_argument("--slug", action="append", default=[],
                    help="restrict to this slug; repeatable")
    ap.add_argument("--difficulty", choices=["Easy", "Medium", "Hard"],
                    help="restrict to one difficulty")
    ap.add_argument("--data-only", action="store_true",
                    help="skip the execution pass (still needs the database)")
    ap.add_argument("--fail-on-skip", action="store_true",
                    help="treat a missing reference_solution as a failure")
    ap.add_argument("--quiet", action="store_true",
                    help="print only failures and the summary")
    return ap.parse_args()


def main():
    args = parse_cli()

    with SessionLocal() as db:
        stmt = select(Problem).order_by(Problem.id)
        if args.slug:
            stmt = stmt.where(Problem.slug.in_(args.slug))
        if args.difficulty:
            stmt = stmt.where(Problem.difficulty == args.difficulty)

        # A gate is only useful if a failure is legible. An unreachable
        # database is an environment problem, not a catalogue defect, so it
        # exits 2 (distinct from 1 = something is actually wrong with the
        # catalogue) and says what to start rather than raising.
        try:
            problems = list(db.scalars(stmt))
        except OperationalError as exc:
            print("ERROR: cannot reach the database.")
            print(f"  {str(exc.orig).strip().splitlines()[0]}")
            print("\nUsually this means Postgres is not running. Start it with:")
            print("  open -a Docker            # wait for the whale to settle")
            print("  docker compose up -d db")
            print("  alembic upgrade head && python3 scripts/seed_problems.py")
            return 2

        if not problems:
            print("ERROR: no problems matched. Is the database seeded?")
            print("  docker compose up -d db && alembic upgrade head "
                  "&& python3 scripts/seed_problems.py")
            return 2

        if args.slug:
            missing = set(args.slug) - {p.slug for p in problems}
            if missing:
                print(f"ERROR: slug(s) not found in the catalogue: {sorted(missing)}")
                return 2

        print(LINE)
        print(f"CATALOGUE VERIFICATION GATE -- {len(problems)} problem(s)")
        print(LINE)

        # ---------------------------------------------------------- pass 1
        print("\nPASS 1 -- DATA VALIDATION")
        print(RULE)
        data_failed, data_warned = [], []
        for p in problems:
            errors, warnings = validate_data(p)
            if errors:
                data_failed.append(p.slug)
                print(f"FAIL  {p.slug}")
                for e in errors:
                    print(f"        {e}")
            elif warnings:
                data_warned.append(p.slug)
                if not args.quiet:
                    print(f"WARN  {p.slug}")
                for w in warnings:
                    print(f"        {w}")
            elif not args.quiet:
                print(f"ok    {p.slug}")

        # Explicit count for the defect named in the selection criteria.
        pair_mismatch = sum(
            1 for p in problems
            for t in (p.sample_tests or []) + (p.hidden_tests or [])
            if not isinstance(t, dict)
            or t.get("args_raw") in (None, [])
            or t.get("expected") is None
        )
        print(f"\n  input / expected-output pairing defects: {pair_mismatch}")
        print(f"  data: {len(problems) - len(data_failed)} passed, "
              f"{len(data_failed)} failed, {len(data_warned)} with warnings")

        # ---------------------------------------------------------- pass 2
        exec_passed, exec_failed, exec_skipped = [], [], []
        if args.data_only:
            print("\nPASS 2 -- EXECUTION: skipped (--data-only)")
        else:
            print("\nPASS 2 -- EXECUTION AGAINST THE LIVE JUDGE")
            print(RULE)
            for p in problems:
                if not (p.reference_solution or "").strip():
                    exec_skipped.append(p.slug)
                    if not args.quiet:
                        print(f"SKIP  {p.slug:<52} no reference solution")
                    continue

                tests = p.hidden_tests or p.sample_tests or []
                origin = "hidden" if p.hidden_tests else "sample"
                if not tests:
                    exec_failed.append(p.slug)
                    print(f"FAIL  {p.slug:<52} no tests to run")
                    continue

                try:
                    result = judge(p, p.reference_solution, tests)
                except JudgeError as exc:
                    exec_failed.append(p.slug)
                    print(f"FAIL  {p.slug:<52} judge error: {exc}")
                    continue
                except Exception as exc:  # docker down, socket missing, etc.
                    exec_failed.append(p.slug)
                    print(f"FAIL  {p.slug:<52} {type(exc).__name__}: {exc}")
                    continue

                verdict = result["verdict"]
                if verdict == "Accepted":
                    exec_passed.append(p.slug)
                    if not args.quiet:
                        print(f"PASS  {p.slug:<52} Accepted "
                              f"({len(tests)} {origin}, "
                              f"{result.get('runtime_ms', '?')}ms)")
                else:
                    exec_failed.append(p.slug)
                    print(f"FAIL  {p.slug:<52} {verdict} "
                          f"({len(tests)} {origin} tests)")
                    print(f"        comparison={p.comparison}  "
                          f"failed_test_index={result.get('failed_test_index')}")
                    if result.get("expected_output") is not None:
                        print(f"        expected={result.get('expected_output')}")
                        print(f"        actual  ={result.get('actual_output')}")
                    elif result.get("stderr"):
                        print(f"        {str(result['stderr']).strip()[:400]}")

        # ---------------------------------------------------------- summary
        total = len(problems)
        verified = len(exec_passed)
        print("\n" + LINE)
        print("SUMMARY")
        print(LINE)
        print(f"  problems in scope           {total}")
        print(f"  data validation passed      {total - len(data_failed)}")
        print(f"  data validation failed      {len(data_failed)}")
        if not args.data_only:
            print(f"  verified by execution       {verified}"
                  f"   ({verified / total * 100:.0f}% coverage)")
            print(f"  execution failed            {len(exec_failed)}")
            print(f"  skipped, no reference       {len(exec_skipped)}")

        failed = bool(data_failed or exec_failed)
        if args.fail_on_skip and exec_skipped:
            failed = True
            print("\n  --fail-on-skip: uncovered problems count as failures")

        print()
        if failed:
            if data_failed:
                print(f"  data failures     : {', '.join(sorted(data_failed))}")
            if exec_failed:
                print(f"  execution failures: {', '.join(sorted(exec_failed))}")
            print("\n*** GATE FAILED ***")
            return 1

        print("*** GATE PASSED ***")
        if exec_skipped and not args.data_only:
            print(f"    {len(exec_skipped)} problem(s) unverified for want of a "
                  f"reference solution -- see coverage above.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
