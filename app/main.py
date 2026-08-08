from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import auth, execute, problems

app = FastAPI(
    title="GlowingStar API",
    version="0.1.0",
    description="Headless LeetCode-core API service",
)

app.include_router(auth.router)
app.include_router(problems.router)
app.include_router(execute.router)


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
