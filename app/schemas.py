from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    created_at: datetime


class UserProfile(UserOut):
    total_solved: int
    total_submissions: int


class ProblemSummary(BaseModel):
    id: int
    slug: str
    title: str
    difficulty: str
    tags: list[str]
    sample_test_count: int
    is_solved: bool | None = None


class ProblemDetail(ProblemSummary):
    description: str
    constraints: str | None
    code_templates: dict
    sample_tests: list[dict]


class RunRequest(BaseModel):
    problem_id: int
    language: str = "python3"
    user_code: str
    custom_input: str | None = None


class CaseResult(BaseModel):
    index: int
    input: str | None = None
    expected: str | None = None
    actual: str | None = None
    passed: bool | None = None
    runtime_ms: int | None = None
    error: str | None = None


class RunResponse(BaseModel):
    status: str
    stdout: str
    stderr: str
    runtime_ms: int
    results: list[CaseResult]


class SubmitRequest(BaseModel):
    problem_id: int
    language: str = "python3"
    user_code: str


class SubmitResponse(BaseModel):
    submission_id: int
    verdict: str
    runtime_ms: int | None = None
    total_tests: int
    failed_test_index: int | None = None
    expected_output: str | None = None
    actual_output: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    is_solved: bool


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    language: str
    verdict: str
    runtime_ms: int | None
    failed_test_index: int | None
    created_at: datetime
