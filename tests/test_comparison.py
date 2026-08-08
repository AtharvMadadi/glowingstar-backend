"""Unit tests for the judge's output comparator (Week 3, Task 3).

Pure-function tests: no Docker, no Postgres, no container startup. Exercises
outputs_match, the single function all four comparison modes and the judging
pipeline route through -- the same function judge() and dry_run() call to
decide Accepted vs Wrong Answer.

Run: pytest tests/test_comparison.py -v
"""

import pytest

from app.judge import outputs_match


# ---------------------------------------------------------------------------
# exact
# ---------------------------------------------------------------------------

class TestExactMode:
    """mode='exact': plain equality, no canonicalization applied."""

    def test_accepts_identical_lists(self):
        assert outputs_match([0, 1], [0, 1], "exact") is True

    def test_rejects_reordered_lists(self):
        # exact mode is order-sensitive by design; this is what separates it
        # from 'unordered' below.
        assert outputs_match([1, 0], [0, 1], "exact") is False

    def test_accepts_identical_strings(self):
        assert outputs_match("hello", "hello", "exact") is True

    def test_rejects_trailing_whitespace_difference(self):
        # A single trailing space is enough to fail exact mode. Confirms the
        # comparator does NOT trim whitespace on your behalf.
        assert outputs_match("hello ", "hello", "exact") is False

    def test_rejects_leading_whitespace_difference(self):
        assert outputs_match(" hello", "hello", "exact") is False

    def test_accepts_int_and_equal_float(self):
        # Python's numeric equality treats 5 == 5.0 as True. Documented as
        # intentional/standard judge behaviour: a solution returning 5.0
        # where 5 is expected shouldn't be marked wrong for that alone.
        assert outputs_match(5, 5.0, "exact") is True

    def test_rejects_different_numeric_value(self):
        assert outputs_match(5, 6, "exact") is False

    def test_rejects_tuple_expected_against_list_actual(self):
        # DATA-AUTHORING GOTCHA for Task 5: actual values are always JSON
        # round-tripped through the judge container, so a Solution can never
        # hand back a native Python tuple by the time it reaches this
        # function -- JSON has no tuple type, so it always arrives as a
        # list. But the *expected* value comes from ast.literal_eval on
        # whatever a human typed into the seed data. If that string uses
        # parens, e.g. "(0, 1)", instead of brackets, "[0, 1]", expected
        # parses to a tuple -- and a tuple never equals a list in Python,
        # even with identical elements. A correct reference solution would
        # be marked Wrong Answer for this reason alone. When authoring
        # hidden_tests expected outputs in Task 5, always use bracket
        # syntax for list-shaped answers.
        assert outputs_match([0, 1], (0, 1), "exact") is False


# ---------------------------------------------------------------------------
# unordered
# ---------------------------------------------------------------------------

class TestUnorderedMode:
    """mode='unordered': list contents match regardless of order."""

    def test_accepts_reordered_list(self):
        assert outputs_match([1, 0], [0, 1], "unordered") is True

    def test_accepts_identical_order_too(self):
        assert outputs_match([0, 1], [0, 1], "unordered") is True

    def test_rejects_genuine_mismatch_same_length(self):
        assert outputs_match([1, 1], [0, 1], "unordered") is False

    def test_rejects_different_length(self):
        assert outputs_match([0, 1, 2], [0, 1], "unordered") is False

    def test_accepts_reordered_list_with_duplicates(self):
        assert outputs_match([2, 1, 1], [1, 2, 1], "unordered") is True

    def test_rejects_duplicate_count_mismatch(self):
        # Same set of distinct values, different multiplicities -- must
        # still fail. Confirms this is a multiset comparison, not a set
        # comparison that would incorrectly collapse duplicates.
        assert outputs_match([1, 1, 2], [1, 2, 2], "unordered") is False


# ---------------------------------------------------------------------------
# unordered_nested
# ---------------------------------------------------------------------------

class TestUnorderedNestedMode:
    """mode='unordered_nested': order ignored at both the outer list level
    and within each inner list (adjacency lists, list-of-pairs, etc)."""

    def test_accepts_reordering_at_both_levels(self):
        assert outputs_match(
            [[4, 3], [2, 1]], [[1, 2], [3, 4]], "unordered_nested"
        ) is True

    def test_accepts_outer_reorder_only(self):
        assert outputs_match(
            [[3, 4], [1, 2]], [[1, 2], [3, 4]], "unordered_nested"
        ) is True

    def test_accepts_inner_reorder_only(self):
        assert outputs_match(
            [[1, 2], [4, 3]], [[1, 2], [3, 4]], "unordered_nested"
        ) is True

    def test_rejects_genuine_mismatch(self):
        assert outputs_match(
            [[1, 2], [3, 5]], [[1, 2], [3, 4]], "unordered_nested"
        ) is False

    def test_rejects_element_moved_to_wrong_group(self):
        # Same raw numbers overall, grouped differently -- must fail.
        # Confirms grouping is preserved, not flattened into one multiset.
        assert outputs_match(
            [[1, 3], [2, 4]], [[1, 2], [3, 4]], "unordered_nested"
        ) is False


# ---------------------------------------------------------------------------
# float
# ---------------------------------------------------------------------------

class TestFloatMode:
    """mode='float': both values rounded to 5 decimal places before
    comparison."""

    def test_accepts_difference_inside_5th_decimal(self):
        # 6th-decimal difference of 4 rounds away cleanly.
        assert outputs_match(0.123454, 0.123450, "float") is True

    def test_rejects_difference_crossing_5th_decimal(self):
        # 6th-decimal difference of 6 rounds the 5th decimal up and
        # produces a genuinely different value.
        assert outputs_match(0.123456, 0.123450, "float") is False

    def test_accepts_exact_match(self):
        assert outputs_match(3.14159, 3.14159, "float") is True

    def test_rejects_integer_part_mismatch(self):
        assert outputs_match(2.00000, 3.00000, "float") is False

    def test_accepts_negative_values_within_tolerance(self):
        assert outputs_match(-0.123454, -0.123450, "float") is True

    def test_rejects_negative_values_crossing_boundary(self):
        assert outputs_match(-0.123456, -0.123450, "float") is False


# ---------------------------------------------------------------------------
# Known defect, filed not fixed -- see PR notes
# ---------------------------------------------------------------------------

class TestBooleanCoercion:
    """outputs_match special-cases booleans: if EITHER value is a bool, it
    compares bool(actual) == bool(expected) instead of canonicalizing
    normally. Correct when both sides are genuinely boolean-shaped
    (True/False/0/1). NOT correct when one side is a bool and the other is
    an unrelated truthy/falsy value of a completely different type -- a
    list, string, or dict -- which this special case incorrectly accepts
    purely because Python considers it truthy.

    A boolean-returning problem where a submission mistakenly returns a
    non-empty string or list instead of True would be marked Accepted here.
    Real correctness gap in the live judge, not hypothetical.

    Filed as xfail rather than fixed: fixing the comparator is out of scope
    for "write unit tests for the comparator" (Task 3). This keeps the
    defect documented and CI green, and makes it fail loudly if anyone
    "fixes" it in a way that doesn't actually fix it.
    """

    def test_accepts_int_one_as_true(self):
        # Documents existing, probably-intentional leniency: many
        # LeetCode-style solutions return 0/1 for boolean problems.
        assert outputs_match(1, True, "exact") is True

    def test_accepts_int_zero_as_false(self):
        assert outputs_match(0, False, "exact") is True

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "known defect: outputs_match's bool special-case matches on "
            "Python truthiness alone, so a wrong-typed truthy value (here, "
            "a non-empty string) is incorrectly accepted against an "
            "expected True. See TestBooleanCoercion docstring."
        ),
    )
    def test_rejects_wrong_type_truthy_value_against_true(self):
        assert outputs_match("no", True, "exact") is False

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "known defect: same root cause as "
            "test_rejects_wrong_type_truthy_value_against_true, mirrored "
            "for an empty-list actual against expected False."
        ),
    )
    def test_rejects_wrong_type_falsy_value_against_false(self):
        assert outputs_match([], False, "exact") is False
