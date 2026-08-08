# GlowingStar Backend

A headless LeetCode-style API service: problem catalogue, user accounts, and a
sandboxed judge that executes submitted code and returns a verdict. Fully
testable through Swagger, Postman, or cURL — no front end required.

## Quick start

Requires Docker Desktop (running) and nothing else.

```bash
git clone <repo-url> && cd glowingstar-backend
docker compose up --build
```

Then open **http://localhost:8000/docs**.

On first boot the API waits for Postgres, applies migrations, seeds 50 problems,
pulls the judge runtime image, and starts serving. No manual setup steps.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | – | Create account, returns JWT |
| POST | `/api/v1/auth/login` | – | Authenticate, returns JWT |
| GET | `/api/v1/auth/me` | JWT | Profile + solved/submission counts |
| GET | `/api/v1/problems` | optional | List; filter by `difficulty`, `tag` |
| GET | `/api/v1/problems/{id_or_slug}` | optional | Full statement, templates, samples |
| GET | `/api/v1/problems/{id}/submissions` | JWT | Caller's history for one problem |
| POST | `/api/v1/execute/run` | JWT | Dry run against samples or custom input |
| POST | `/api/v1/execute/submit` | JWT | Full judge, records submission |
| GET | `/health` | – | Liveness + database connectivity |

Authentication is `Authorization: Bearer <token>`. In Swagger, use the
**Authorize** button.

### Example

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","email":"demo@example.com","password":"demopass123"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST localhost:8000/api/v1/execute/submit \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"problem_id":1,"language":"python3","user_code":"class Solution:\n    def twoSum(self, nums, target):\n        seen={}\n        for i,n in enumerate(nums):\n            if target-n in seen: return [seen[target-n],i]\n            seen[n]=i"}'
```

## Verdicts

| Verdict | Meaning |
|---|---|
| `Accepted` | All test cases passed |
| `Wrong Answer` | Output mismatch; response carries the failing index, expected, and actual |
| `Time Limit Exceeded` | Exceeded the 3-second cap |
| `Compile Error` | Syntax or indentation error |
| `Runtime Error` | Exception, memory limit, or abnormal exit |

An `Accepted` verdict marks the problem solved for that user. Solved state is
**derived** — a problem counts as solved when an Accepted submission exists —
rather than stored as a flag, so the two can never disagree.

## Sandbox design

Submitted code runs in a disposable container, one per execution:

- `--network none` — no outbound or inbound network
- `--memory 256m` — capped allocation
- `--pids-limit 64` — blocks fork bombs
- `--read-only` + `--user 65534:65534` — non-root, immutable filesystem, small tmpfs only
- `--rm` — guaranteed teardown

The program is piped to the container on **stdin**, not bind-mounted, so the
judge behaves identically whether the API runs on the host or in a container
(where a container-local path would be meaningless to the host daemon).

The 3-second limit is enforced inside the container with `SIGALRM`, with a
subprocess timeout as a backstop should user code swallow the alarm.

### The Docker socket tradeoff

`docker-compose.yml` mounts `/var/run/docker.sock` into the API container so it
can launch judge containers. This grants the API effective root on the host and
is **not** suitable for production; a real deployment would use a dedicated
execution service, gVisor/Firecracker isolation, or a remote worker pool. It is
accepted here because the target is a locally-run MVP, and the alternative —
a hosted execution API — was unavailable (the public Piston API moved behind
authorization in February 2026).

## Output comparison

Exact string comparison is wrong for many problems. Each row carries a
`comparison` mode:

| Mode | Applies to | Behaviour |
|---|---|---|
| `exact` | Most problems | Direct equality |
| `unordered` | "return in any order" | Outer list sorted before comparing |
| `unordered_nested` | Lists of lists, e.g. 3Sum, Group Anagrams | Both levels sorted |
| `float` | Median of Two Sorted Arrays | Rounded to 5 decimal places |

Without this, a correct Two Sum solution returning `[1,0]` instead of `[0,1]`
would be judged Wrong Answer.

## Problem selection

The 50 seeded problems were filtered from a 3,991-record corpus collected in
Phase 1 (`scripts/select_seed.py`). Excluded by design:

- **Linked list / tree / graph** — require constructing and serialising custom
  node objects, outside the scope of a positional-argument judge
- **Design / iterator problems** — graded on a sequence of method calls, a
  different evaluation model entirely
- **In-place / void return** — nothing is returned, so nothing can be compared
- **Premium** — statements not publicly available
- **Example/testcase count mismatch** — inputs and expected outputs are paired
  positionally; a mismatch would silently produce false verdicts

Remaining candidates were ranked by popularity and quota-filled to 25 Easy /
20 Medium / 5 Hard.

## Language support

Starter templates are served for **Python, Java, and C++**. Execution is
implemented for **Python 3** only; other languages return `400` with an
explanatory message rather than failing opaquely. Extending it means adding a
per-language harness — the judging, comparison, and persistence layers are
language-agnostic already.

## Layout
## Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db
alembic upgrade head
python scripts/seed_problems.py
fastapi dev app/main.py
```

Verify the judge independently:

```bash
python scripts/test_judge.py
```

## Data provenance

Problem statements originate from LeetCode, collected in Phase 1 for
educational use. The corpus is not redistributed in full — only the 50 selected
problems are bundled, in `scripts/seed_data.json`.

## Known limitations

- **Hidden test cases are authored for 10 of the 50 problems** (see
  `scripts/generate_hidden_tests.py`).
  `submit` evaluates against `hidden_tests` when present, falling back to the
  public sample cases otherwise. Extending coverage to the remaining 40
  problems is follow-up work.
- Judging is Python-only (see above).
- Container startup adds roughly one second of latency per execution.
- No JWT secret is committed. A real value must be supplied via `JWT_SECRET`
  in production; local development without one gets an ephemeral secret
  generated at boot (see `app/config.py`), which invalidates tokens on restart.
