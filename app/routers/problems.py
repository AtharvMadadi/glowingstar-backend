from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_optional_user
from app.models import Problem, Submission, User
from app.schemas import ProblemDetail, ProblemSummary, SubmissionOut

router = APIRouter(prefix="/api/v1/problems", tags=["problems"])

DIFFICULTIES = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}


def solved_slugs(db: Session, user: User | None) -> set[int]:
    if user is None:
        return set()
    rows = db.scalars(
        select(Submission.problem_id)
        .where(Submission.user_id == user.id, Submission.verdict == "Accepted")
        .distinct()
    )
    return set(rows)


@router.get("", response_model=list[ProblemSummary])
def list_problems(
    difficulty: str | None = Query(None, description="Easy, Medium, or Hard"),
    tag: str | None = Query(None, description="e.g. Array, String, Hash Table"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    stmt = select(Problem)

    if difficulty is not None:
        key = difficulty.strip().lower()
        if key not in DIFFICULTIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="difficulty must be Easy, Medium, or Hard",
            )
        stmt = stmt.where(Problem.difficulty == DIFFICULTIES[key])

    if tag is not None:
        stmt = stmt.where(
            text(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(problems.tags) AS t"
                " WHERE lower(t) = lower(:tag))"
            ).bindparams(tag=tag.strip())
        )

    stmt = stmt.order_by(Problem.id).limit(limit).offset(offset)
    problems = db.scalars(stmt).all()

    solved = solved_slugs(db, user)
    return [
        ProblemSummary(
            id=p.id,
            slug=p.slug,
            title=p.title,
            difficulty=p.difficulty,
            tags=p.tags or [],
            sample_test_count=len(p.sample_tests or []),
            is_solved=(p.id in solved) if user else None,
        )
        for p in problems
    ]


@router.get("/{id_or_slug}", response_model=ProblemDetail)
def get_problem(
    id_or_slug: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    if id_or_slug.isdigit():
        problem = db.get(Problem, int(id_or_slug))
    else:
        problem = db.scalar(select(Problem).where(Problem.slug == id_or_slug))

    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found"
        )

    is_solved = None
    if user is not None:
        is_solved = (
            db.scalar(
                select(func.count(Submission.id)).where(
                    Submission.user_id == user.id,
                    Submission.problem_id == problem.id,
                    Submission.verdict == "Accepted",
                )
            )
            or 0
        ) > 0

    return ProblemDetail(
        id=problem.id,
        slug=problem.slug,
        title=problem.title,
        difficulty=problem.difficulty,
        tags=problem.tags or [],
        sample_test_count=len(problem.sample_tests or []),
        is_solved=is_solved,
        description=problem.description,
        constraints=problem.constraints,
        code_templates=problem.code_templates or {},
        sample_tests=[
            {
                "input": t.get("display_input"),
                "output": t.get("expected"),
                "explanation": t.get("explanation"),
            }
            for t in (problem.sample_tests or [])
        ],
    )


@router.get("/{id_or_slug}/submissions", response_model=list[SubmissionOut])
def problem_submissions(
    id_or_slug: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submission history for the logged-in user on a specific problem."""
    if id_or_slug.isdigit():
        problem = db.get(Problem, int(id_or_slug))
    else:
        problem = db.scalar(select(Problem).where(Problem.slug == id_or_slug))
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found"
        )

    rows = db.scalars(
        select(Submission)
        .where(Submission.user_id == user.id, Submission.problem_id == problem.id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
    ).all()
    return rows
