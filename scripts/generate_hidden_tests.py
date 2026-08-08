#!/usr/bin/env python3
"""Week 3, Task 5 -- hidden-test generation pipeline.

This is the pipeline itself, not its output. Running it end to end:

  1. Reference solution per problem (REFERENCE_SOURCE below) -- the single
     source of truth. Each entry is exec()'d to obtain a live Solution
     class, so the code that COMPUTES expected outputs here is byte-for-byte
     the same code that gets stored in reference_solution and re-submitted
     through the live judge in step 4 -- not two hand-synced copies.
  2. Hidden inputs per problem (generator functions defined below) --
     generated where the input shape permits, hand-constructed for edge
     cases: empty, single element, duplicates, boundary values, maximum
     constraints. two-sum's generator additionally validates single-answer
     uniqueness by brute force, since its own constraint states "only one
     valid answer exists" and a naively-random array could violate that.
  3. Expected outputs: produced by actually running the reference solution
     against each generated input (this script), then round-tripped through
     the real parse_args -> parse_expected -> outputs_match path before
     being accepted, to catch any stringification mismatch before it's
     written to disk.
  4. Verification pass: scripts/verify_task5.py, run separately against the
     live judge once this script's output has been re-seeded.

Run:
    python3 scripts/generate_hidden_tests.py
    python3 scripts/seed_problems.py
    python3 scripts/verify_task5.py

Regenerating reproduces the exact same hidden tests: the RNG is seeded.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.judge import outputs_match, parse_args, parse_expected  # noqa: E402

random.seed(20260807)

SEED_DATA_PATH = Path(__file__).resolve().parent / "seed_data.json"

# ---------------------------------------------------------------------------
# Step 1 -- reference solutions. Single source of truth: exec()'d below to
# get a live class for computing expected outputs, and stored verbatim into
# each problem's reference_solution field for the live-judge verification
# pass. There is no second copy of this logic anywhere else in the repo.
# ---------------------------------------------------------------------------

REFERENCE_SOURCE = {
    "two-sum": '''\
class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        seen = {}
        for i, x in enumerate(nums):
            need = target - x
            if need in seen:
                return [seen[need], i]
            seen[x] = i
        raise ValueError("no solution")
''',
    "valid-parentheses": '''\
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
        return not stack
''',
    "merge-intervals": '''\
class Solution:
    def merge(self, intervals: List[List[int]]) -> List[List[int]]:
        if not intervals:
            return []
        ordered = sorted(intervals, key=lambda iv: iv[0])
        out = [list(ordered[0])]
        for start, end in ordered[1:]:
            if start <= out[-1][1]:
                out[-1][1] = max(out[-1][1], end)
            else:
                out.append([start, end])
        return out
''',
    "binary-search": '''\
class Solution:
    def search(self, nums: List[int], target: int) -> int:
        lo, hi = 0, len(nums) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if nums[mid] == target:
                return mid
            if nums[mid] < target:
                lo = mid + 1
            else:
                hi = mid - 1
        return -1
''',
    "climbing-stairs": '''\
class Solution:
    def climbStairs(self, n: int) -> int:
        a, b = 1, 1
        for _ in range(n):
            a, b = b, a + b
        return a
''',
    "3sum": '''\
class Solution:
    def threeSum(self, nums: List[int]) -> List[List[int]]:
        nums = sorted(nums)
        n = len(nums)
        out = []
        for i in range(n - 2):
            if i > 0 and nums[i] == nums[i - 1]:
                continue
            if nums[i] > 0:
                break
            lo, hi = i + 1, n - 1
            while lo < hi:
                s = nums[i] + nums[lo] + nums[hi]
                if s < 0:
                    lo += 1
                elif s > 0:
                    hi -= 1
                else:
                    out.append([nums[i], nums[lo], nums[hi]])
                    lo += 1
                    hi -= 1
                    while lo < hi and nums[lo] == nums[lo - 1]:
                        lo += 1
                    while lo < hi and nums[hi] == nums[hi + 1]:
                        hi -= 1
        return out
''',
    "group-anagrams": '''\
class Solution:
    def groupAnagrams(self, strs: List[str]) -> List[List[str]]:
        groups = {}
        for s in strs:
            key = "".join(sorted(s))
            groups.setdefault(key, []).append(s)
        return list(groups.values())
''',
    "longest-substring-without-repeating-characters": '''\
class Solution:
    def lengthOfLongestSubstring(self, s: str) -> int:
        last_seen = {}
        start = 0
        best = 0
        for i, ch in enumerate(s):
            if ch in last_seen and last_seen[ch] >= start:
                start = last_seen[ch] + 1
            last_seen[ch] = i
            best = max(best, i - start + 1)
        return best
''',
    "search-in-rotated-sorted-array": '''\
class Solution:
    def search(self, nums: List[int], target: int) -> int:
        lo, hi = 0, len(nums) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if nums[mid] == target:
                return mid
            if nums[lo] <= nums[mid]:
                if nums[lo] <= target < nums[mid]:
                    hi = mid - 1
                else:
                    lo = mid + 1
            else:
                if nums[mid] < target <= nums[hi]:
                    lo = mid + 1
                else:
                    hi = mid - 1
        return -1
''',
    "product-of-array-except-self": '''\
class Solution:
    def productExceptSelf(self, nums: List[int]) -> List[int]:
        n = len(nums)
        out = [1] * n
        left = 1
        for i in range(n):
            out[i] = left
            left *= nums[i]
        right = 1
        for i in range(n - 1, -1, -1):
            out[i] *= right
            right *= nums[i]
        return out
''',
}

METHOD_NAME = {
    "two-sum": "twoSum",
    "valid-parentheses": "isValid",
    "merge-intervals": "merge",
    "binary-search": "search",
    "climbing-stairs": "climbStairs",
    "3sum": "threeSum",
    "group-anagrams": "groupAnagrams",
    "longest-substring-without-repeating-characters": "lengthOfLongestSubstring",
    "search-in-rotated-sorted-array": "search",
    "product-of-array-except-self": "productExceptSelf",
}


def load_solution(slug):
    """exec() the stored source to get a live Solution instance -- the same
    mechanism the real judge uses (see app/judge.py's HARNESS), so there is
    no behavioural gap between 'the code that generated this data' and 'the
    code that will be re-submitted to verify it'."""
    ns = {"List": list.__class__.__mro__[0]}  # placeholder, replaced below
    import typing
    ns = {"List": typing.List, "Dict": typing.Dict}
    exec(REFERENCE_SOURCE[slug], ns)
    return ns["Solution"]()


# ---------------------------------------------------------------------------
# Step 2 -- hidden input generation. Deterministic generators and edge cases.
# ---------------------------------------------------------------------------

def fmt(v):
    return repr(v)


def case(args, display, note=None):
    return {"args": args, "display": display, "note": note}


def two_sum_cases():
    out = []

    def count_pairs(nums, target):
        n = 0
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    n += 1
        return n

    def gen_unique_pair_array(size, lo, hi, target):
        for _ in range(500):
            nums = [random.randint(lo, hi) for _ in range(size - 2)]
            a = random.randint(lo, hi)
            b = target - a
            if not (lo <= b <= hi):
                continue
            pos = sorted(random.sample(range(size), 2))
            arr = nums[:]
            arr.insert(pos[0], a)
            arr.insert(pos[1], b)
            if len(arr) != size:
                continue
            if count_pairs(arr, target) == 1:
                return arr
        raise RuntimeError("could not generate a unique-answer two-sum case")

    arr = gen_unique_pair_array(6, -50, 50, 10)
    out.append(case([arr, 10], f"nums = {arr}, target = 10"))
    arr = gen_unique_pair_array(10, -1000, 1000, 0)
    out.append(case([arr, 0], f"nums = {arr}, target = 0"))
    out.append(case([[1, 2], 3], "nums = [1,2], target = 3", "minimum length (2 elements)"))
    out.append(case([[-3, 4, 3, 90], 0], "nums = [-3,4,3,90], target = 0", "negative + positive mix, sum to zero"))
    out.append(case(
        [[10**9, -10**9, 5, 6], 0], f"nums = [{10**9},{-10**9},5,6], target = 0",
        "boundary magnitude values (1e9)"))
    out.append(case([[5, 5, 11], 10], "nums = [5,5,11], target = 10", "duplicate values forming the answer"))
    return out


def valid_parens_cases():
    out = []
    charset = "()[]{}"

    def random_valid(n_pairs):
        stack, s = [], []
        remaining_open = n_pairs
        remaining_close = 0
        while remaining_open > 0 or remaining_close > 0:
            can_open = remaining_open > 0
            can_close = remaining_close > 0
            if can_open and (not can_close or random.random() < 0.5):
                t = random.choice("([{")
                s.append(t)
                stack.append(t)
                remaining_open -= 1
                remaining_close += 1
            else:
                t = stack.pop()
                s.append({'(': ')', '[': ']', '{': '}'}[t])
                remaining_close -= 1
        return "".join(s)

    valid = random_valid(6)
    out.append(case([valid], f's = "{valid}"', "generated, well-formed, mixed bracket types"))
    invalid = "".join(random.choice(charset) for _ in range(9))
    out.append(case([invalid], f's = "{invalid}"', "generated, random -- likely malformed"))
    out.append(case(["("], 's = "("', "single unmatched open, odd length"))
    out.append(case([")"], 's = ")"', "single unmatched close"))
    out.append(case(["([)]"], 's = "([)]"', "interleaved wrong order, classic trap"))
    out.append(case(["(" * 100 + ")" * 100], 's = "("*100 + ")"*100', "deep nesting, all one type"))
    out.append(case(["()" * 5000], 's = "()"*5000', "max-length boundary, 10000 chars"))
    return out


def merge_intervals_cases():
    out = []

    def gen(n, span):
        ivs = []
        for _ in range(n):
            a = random.randint(0, span)
            b = random.randint(a, min(span, a + random.randint(0, span // 4 + 1)))
            ivs.append([a, b])
        random.shuffle(ivs)
        return ivs

    ivs = gen(8, 40)
    out.append(case([ivs], f"intervals = {ivs}", "generated, unsorted, overlaps likely"))
    ivs = gen(12, 20)
    out.append(case([ivs], f"intervals = {ivs}", "generated, dense range -- heavy overlap"))
    out.append(case([[[1, 4]]], "intervals = [[1,4]]", "single interval, nothing to merge"))
    out.append(case([[[1, 4], [4, 5]]], "intervals = [[1,4],[4,5]]", "touching endpoints must merge"))
    out.append(case([[[1, 4], [5, 6]]], "intervals = [[1,4],[5,6]]", "adjacent but not touching, must NOT merge"))
    out.append(case([[[1, 4], [2, 3]]], "intervals = [[1,4],[2,3]]", "one interval fully contained in another"))
    out.append(case([[[1, 4], [1, 4], [1, 4]]], "intervals = [[1,4],[1,4],[1,4]]", "exact duplicate intervals"))
    return out


def binary_search_cases():
    out = []

    def gen(n):
        return sorted(random.sample(range(-500, 500), n))

    nums = gen(15)
    target = random.choice(nums)
    out.append(case([nums, target], f"nums = {nums}, target = {target}", "generated, target present"))
    nums = gen(15)
    target = max(nums) + 1
    out.append(case([nums, target], f"nums = {nums}, target = {target}", "generated, target absent"))
    out.append(case([[5], 5], "nums = [5], target = 5", "single element, present"))
    out.append(case([[5], -1], "nums = [5], target = -1", "single element, absent"))
    nums = gen(9)
    out.append(case([nums, nums[0] - 1], f"nums = {nums}, target = {nums[0]-1}", "target below range"))
    out.append(case([nums, nums[-1] + 1], f"nums = {nums}, target = {nums[-1]+1}", "target above range"))
    out.append(case([nums, nums[0]], f"nums = {nums}, target = {nums[0]}", "target at left boundary"))
    out.append(case([nums, nums[-1]], f"nums = {nums}, target = {nums[-1]}", "target at right boundary"))
    return out


def climbing_stairs_cases():
    return [
        case([1], "n = 1", "base case, not covered by samples"),
        case([10], "n = 10"),
        case([20], "n = 20", "generated mid-range"),
        case([45], "n = 45", "maximum constraint boundary"),
    ]


def three_sum_cases():
    out = []

    def gen(n, span):
        return [random.randint(-span, span) for _ in range(n)]

    nums = gen(12, 20)
    out.append(case([nums], f"nums = {nums}", "generated, small range -- multiple triplets likely"))
    nums = gen(30, 100)
    out.append(case([nums], f"nums = {nums}", "generated, larger set"))
    out.append(case([[0, 0, 0]], "nums = [0,0,0]", "exactly 3 elements, all zero"))
    out.append(case([[1, 2, 3]], "nums = [1,2,3]", "exactly 3 elements, no valid triplet"))
    out.append(case([[0, 0, 0, 0]], "nums = [0,0,0,0]", "heavy duplicates, one unique triplet"))
    out.append(case([[-2, 0, 1, 1, 2]], "nums = [-2,0,1,1,2]", "duplicates requiring dedup logic"))
    return out


def group_anagrams_cases():
    out = []
    words = ["eat", "tea", "tan", "ate", "nat", "bat", "cat", "act", "tac", "rat", "tar", "art"]
    sample = random.sample(words, 8)
    out.append(case([sample], f"strs = {sample}", "generated, mixed anagram groups"))
    sample = [random.choice("abcdefgh") + random.choice("abcdefgh") + random.choice("abcdefgh") for _ in range(10)]
    out.append(case([sample], f"strs = {sample}", "generated, random 3-letter strings"))
    out.append(case([["a"]], 'strs = ["a"]', "single string"))
    out.append(case([[""]], 'strs = [""]', "single empty string -- length 0 is allowed by constraint"))
    out.append(case([["", ""]], 'strs = ["",""]', "multiple empty strings, all anagrams of each other"))
    out.append(case([["abc", "cba", "bac"]], 'strs = ["abc","cba","bac"]', "all mutual anagrams"))
    out.append(case([["abc", "def", "ghi"]], 'strs = ["abc","def","ghi"]', "no anagrams, all singleton groups"))
    out.append(case([["aa", "aa", "aa"]], 'strs = ["aa","aa","aa"]', "identical strings, one group of 3"))
    return out


def lswrc_cases():
    out = []

    def gen(n, alphabet):
        return "".join(random.choice(alphabet) for _ in range(n))

    s = gen(20, "abcde")
    out.append(case([s], f's = "{s}"', "generated, small alphabet -- forces repeats"))
    s = gen(30, "abcdefghijklmnopqrstuvwxyz")
    out.append(case([s], f's = "{s}"', "generated, full alphabet -- longer runs likely"))
    out.append(case([""], 's = ""', "empty string, length 0 is explicitly allowed"))
    out.append(case(["a"], 's = "a"', "single character"))
    out.append(case(["aaaa"], 's = "aaaa"', "all same character"))
    out.append(case(["abcdef"], 's = "abcdef"', "all unique, no repeats at all"))
    out.append(case(["a a!a"], 's = "a a!a"', "spaces and symbols, constraint explicitly allows them"))
    return out


def search_rotated_cases():
    out = []

    def rotate(vals, k):
        k %= len(vals)
        return vals[k:] + vals[:k]

    base = sorted(random.sample(range(-200, 200), 12))
    rotated = rotate(base, random.randint(1, len(base) - 1))
    target = random.choice(rotated)
    out.append(case([rotated, target], f"nums = {rotated}, target = {target}", "generated, rotated, target present"))
    base = sorted(random.sample(range(-200, 200), 12))
    rotated = rotate(base, random.randint(1, len(base) - 1))
    target = max(base) + 50
    out.append(case([rotated, target], f"nums = {rotated}, target = {target}", "generated, rotated, target absent"))
    out.append(case([[1], 1], "nums = [1], target = 1", "single element, present"))
    out.append(case([[7], 3], "nums = [7], target = 3", "single element, absent"))
    out.append(case([[3, 1], 1], "nums = [3,1], target = 1", "two elements, rotated"))
    base = sorted(random.sample(range(-100, 100), 10))
    rotated = rotate(base, 1)
    out.append(case(
        [rotated, rotated[0]], f"nums = {rotated}, target = {rotated[0]}",
        "target exactly at the rotation pivot"))
    return out


def product_except_self_cases():
    out = []

    def gen(n):
        return [random.randint(-30, 30) for _ in range(n)]

    nums = gen(8)
    out.append(case([nums], f"nums = {nums}", "generated, mixed sign, no zeros"))
    nums = gen(6)
    out.append(case([nums], f"nums = {nums}", "generated, second run"))
    out.append(case([[3, 7]], "nums = [3,7]", "minimum length, 2 elements"))
    out.append(case([[1, 0, 3, 4]], "nums = [1,0,3,4]", "single zero -- breaks a division-based approach"))
    out.append(case([[0, 0, 3, 4]], "nums = [0,0,3,4]", "two zeros -- every output must be 0"))
    out.append(case([[-1, -2, -3, -4]], "nums = [-1,-2,-3,-4]", "all negative"))
    out.append(case([[30, 30, 30, 30, 30]], "nums = [30,30,30,30,30]", "boundary magnitude, repeated"))
    return out


GENERATORS = {
    "two-sum": two_sum_cases,
    "valid-parentheses": valid_parens_cases,
    "merge-intervals": merge_intervals_cases,
    "binary-search": binary_search_cases,
    "climbing-stairs": climbing_stairs_cases,
    "3sum": three_sum_cases,
    "group-anagrams": group_anagrams_cases,
    "longest-substring-without-repeating-characters": lswrc_cases,
    "search-in-rotated-sorted-array": search_rotated_cases,
    "product-of-array-except-self": product_except_self_cases,
}


def main():
    data = json.loads(SEED_DATA_PATH.read_text())
    by_slug = {p["slug"]: p for p in data}

    for slug in GENERATORS:
        assert slug in by_slug, f"{slug} not found in seed_data.json"

    print("=" * 78)
    print("STEP 1-3 -- GENERATE, EXECUTE, ROUND-TRIP VERIFY")
    print("=" * 78)

    for slug, gen_fn in GENERATORS.items():
        p = by_slug[slug]
        mode = p["comparison"]
        sol = load_solution(slug)
        method = getattr(sol, METHOD_NAME[slug])

        hidden = []
        for c in gen_fn():
            expected = method(*c["args"])
            entry = {
                "args_raw": [fmt(a) for a in c["args"]],
                "expected": fmt(expected),
                "display_input": c["display"],
                "explanation": c.get("note"),
            }
            # round-trip through the exact path judge() takes before
            # accepting this entry, to catch any stringification mismatch
            # now rather than after it's written to disk
            reparsed_args = parse_args(entry["args_raw"])
            reparsed_expected = parse_expected(entry["expected"])
            reactual = method(*reparsed_args)
            assert outputs_match(reactual, reparsed_expected, mode), (
                f"{slug}: round-trip mismatch on {entry['display_input']}"
            )
            hidden.append(entry)

        # de-dup against sample_tests and within this set
        sample_sigs = {json.dumps(s["args_raw"]) for s in p["sample_tests"]}
        seen = set()
        deduped = []
        for h in hidden:
            sig = json.dumps(h["args_raw"])
            if sig in sample_sigs:
                print(f"  WARN {slug}: dropping a hidden test that duplicates a sample: {h['args_raw']}")
                continue
            if sig in seen:
                print(f"  WARN {slug}: dropping a duplicate hidden test: {h['args_raw']}")
                continue
            seen.add(sig)
            deduped.append(h)

        p["hidden_tests"] = deduped
        p["reference_solution"] = REFERENCE_SOURCE[slug]
        print(f"OK    {slug:<48} {len(deduped)} hidden tests, reference_solution stored")

    SEED_DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    total = sum(len(by_slug[s]["hidden_tests"]) for s in GENERATORS)
    print()
    print(f"wrote {SEED_DATA_PATH}, total hidden tests across 10 problems: {total}")
    print()
    print("Next: python3 scripts/seed_problems.py && python3 scripts/verify_task5.py")


if __name__ == "__main__":
    main()
