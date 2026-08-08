from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.judge import SUPPORTED, JudgeError, dry_run, judge
from app.models import Problem, Submission, User
from app.schemas import RunRequest, RunResponse, SubmitRequest, SubmitResponse

router = APIRouter(prefix="/api/v1/execute", tags=["execute"])

MAX_CODE_CHARS = 20000


def _load(db: Session, problem_id: int, language: str, code: str) -> Problem:
    if language not in SUPPORTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution is supported for {sorted(SUPPORTED)} only; "
                   f"starter templates are provided for other languages.",
        )
    if not code or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user_code is empty"
        )
    if len(code) > MAX_CODE_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"user_code exceeds {MAX_CODE_CHARS} characters",
        )
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found"
        )
    return problem


@router.post("/run", response_model=RunResponse)
def run_code(
    payload: RunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    problem = _load(db, payload.problem_id, payload.language, payload.user_code)
    try:
        return dry_run(
            problem, payload.user_code, problem.sample_tests or [],
            custom_input=payload.custom_input,
        )
    except JudgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post("/submit", response_model=SubmitResponse)
def submit_code(
    payload: SubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    problem = _load(db, payload.problem_id, payload.language, payload.user_code)

    # Hidden tests are authoritative; fall back to samples until authored.
    tests = problem.hidden_tests or problem.sample_tests or []
    if not tests:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No test cases available for this problem",
        )

    try:
        result = judge(problem, payload.user_code, tests)
    except JudgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    submission = Submission(
        user_id=user.id,
        problem_id=problem.id,
        language=payload.language,
        code=payload.user_code,
        verdict=result["verdict"],
        runtime_ms=result.get("runtime_ms"),
        stdout=result.get("stdout"),
        stderr=result.get("stderr"),
        failed_test_index=result.get("failed_test_index"),
        expected_output=result.get("expected_output"),
        actual_output=result.get("actual_output"),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    already = db.scalar(
        select(Submission.id).where(
            Submission.user_id == user.id,
            Submission.problem_id == problem.id,
            Submission.verdict == "Accepted",
        ).limit(1)
    )

    return SubmitResponse(
        submission_id=submission.id,
        verdict=submission.verdict,
        runtime_ms=submission.runtime_ms,
        total_tests=len(tests),
        failed_test_index=submission.failed_test_index,
        expected_output=submission.expected_output,
        actual_output=submission.actual_output,
        stdout=submission.stdout,
        stderr=submission.stderr,
        is_solved=already is not None,
    )
