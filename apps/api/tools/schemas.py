"""Argument schemas. Model output is validated against these before anything runs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class WriteFileArgs(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=2_000_000)


class EditFileArgs(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    find: str = Field(min_length=1)
    replace: str


class ListDirArgs(BaseModel):
    path: str = "."


class SearchCodeArgs(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    glob: str = "**/*"


class RunCommandArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40)
    cwd: str = "."
    timeout_seconds: int = Field(default=120, ge=1, le=900)


class RunTestsArgs(BaseModel):
    suite: str = "all"
    timeout_seconds: int = Field(default=600, ge=1, le=3600)


class GitStatusArgs(BaseModel):
    pass


class GitBranchArgs(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9._/-]{1,120}$")


class GitCommitArgs(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    paths: list[str] = Field(default_factory=list)


class CreatePullRequestArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    base: str = "main"
    head: str
