# Week 3, Task 4 — Multiple-Valid-Answer Audit

Atharv Madadi · 7 August 2026

Reviewed all 50 seeded problems in `scripts/seed_data.json` for cases where
more than one output is valid, per the pre-Task-5 requirement. Every problem
below was checked against its stored `description`, `constraints`, assigned
`comparison` mode, and Python starter return type rather than relying only on
memory of the canonical problem.

## Method

1. Scanned each stored `description` + `constraints` for language allowing
   multiple correct outputs or guaranteeing uniqueness (for example, "any
   order," "any valid," and "only one valid answer exists").
2. Checked every array/list or string-returning problem against its assigned
   comparison mode (`exact`, `unordered`, `unordered_nested`, or `float`).
3. Separately classified exact-mode outputs by actual starter return type so
   every one of the 50 problems appears in exactly one bucket.
4. Verified the final classification has **50 unique slugs and zero overlap**.

## Finding: 1 confirmed defect

**`longest-palindromic-substring`** — mode `exact`. It returns the substring
itself, not its length. The stored example explicitly states that for
`s = "babad"`, both `"bab"` and `"aba"` are valid maximum-length answers.
A single stored expected string can therefore reject a correct submission.

**Resolution: excluded from this week's 10-problem Task 5 batch.** The problem
remains in the catalogue, but no hidden tests are generated for it in this
sprint. A future validator/comparison mode can check whether the submitted
substring satisfies the problem condition instead of comparing it to one
stored witness.

## Caution carried into Task 5 (not a defect)

**`minimum-window-substring`** — also returns a substring, but its stored
statement says the test cases are generated so the answer is unique. It is
therefore safe under `exact` **only if generated hidden inputs preserve that
uniqueness guarantee**.

## Verified clear — complete, non-overlapping classification

### `unordered` / `unordered_nested` problems — 8

| Problem | Mode | Why the mode is appropriate |
|---|---|---|
| `two-sum` | `unordered` | the valid index pair is unique; order of the two indices is not semantically important |
| `3sum` | `unordered_nested` | triplet set is deterministic; outer and inner order may vary |
| `merge-intervals` | `unordered` | merged interval set is deterministic; each `[start, end]` pair remains ordered |
| `generate-parentheses` | `unordered` | valid result set is deterministic; output order is free |
| `group-anagrams` | `unordered_nested` | group order and member order may vary |
| `combination-sum` | `unordered_nested` | valid combination set is deterministic; ordering may vary |
| `letter-combinations-of-a-phone-number` | `unordered` | combination set is deterministic; order is not required |
| `find-all-numbers-disappeared-in-an-array` | `unordered` | missing-number set is deterministic; order is not required |

### Exact-mode numeric scalar (`int`) — 21

`longest-substring-without-repeating-characters`, `maximum-subarray`,
`trapping-rain-water`, `best-time-to-buy-and-sell-stock`,
`container-with-most-water`, `search-in-rotated-sorted-array`,
`find-the-duplicate-number`, `subarray-sum-equals-k`, `number-of-islands`,
`climbing-stairs`, `house-robber`, `longest-consecutive-sequence`,
`majority-element`, `longest-increasing-subsequence`,
`largest-rectangle-in-histogram`, `search-insert-position`, `single-number`,
`roman-to-integer`, `missing-number`, `binary-search`,
`min-cost-climbing-stairs`.

These return one numeric value (length, count, sum, index, or optimum value),
so multiple internal witnesses do not create multiple valid serialized outputs.

### Exact-mode boolean — 9

`valid-parentheses`, `jump-game`, `palindrome-number`, `valid-anagram`,
`contains-duplicate`, `happy-number`, `valid-palindrome`, `is-subsequence`,
`isomorphic-strings`.

Each returns a single boolean result; there is no multiple-answer output-format
ambiguity.

### Exact-mode ordered/list structure — 8

`product-of-array-except-self`,
`find-first-and-last-position-of-element-in-sorted-array`,
`sliding-window-maximum`, `pascals-triangle`, `counting-bits`, `plus-one`,
`squares-of-a-sorted-array`, `next-greater-element-i`.

For each, list position is part of the problem semantics, so `exact` is
appropriate.

### Exact-mode deterministic string — 2

- `add-binary` — canonical binary representation is deterministic.
- `minimum-window-substring` — deterministic under the stored uniqueness
  guarantee; Task 5 must preserve that guarantee when generating inputs.

### Float-mode — 1

`median-of-two-sorted-arrays` — one numeric answer, compared using `float`.

### Confirmed multiple-valid-answer defect — 1

`longest-palindromic-substring` — excluded from the Task 5 batch as described
above.

## Count check

- unordered / unordered_nested: **8**
- exact numeric scalar: **21**
- exact boolean: **9**
- exact ordered/list structure: **8**
- exact deterministic string: **2**
- float: **1**
- confirmed multi-answer defect: **1**

**Total: 50 problems, 50 unique slugs, 0 overlaps.**

**Final result: 1 confirmed multiple-valid-answer problem found and resolved by
exclusion; 1 adjacent uniqueness risk carried forward as a Task 5 generation
constraint; 0 defects in the remaining 48 problems.**
