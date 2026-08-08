from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Submission, User
from app.schemas import Token, UserLogin, UserProfile, UserRegister
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(User).where(
            or_(User.username == payload.username, User.email == payload.email)
        )
    )
    if existing:
        field = "username" if existing.username == payload.username else "email"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That {field} is already registered",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(
        select(User).where(
            or_(User.username == payload.username, User.email == payload.username)
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserProfile)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_solved = db.scalar(
        select(func.count(func.distinct(Submission.problem_id))).where(
            Submission.user_id == user.id, Submission.verdict == "Accepted"
        )
    )
    total_submissions = db.scalar(
        select(func.count(Submission.id)).where(Submission.user_id == user.id)
    )
    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
        total_solved=total_solved or 0,
        total_submissions=total_submissions or 0,
    )
