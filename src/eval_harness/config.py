"""`evals.yaml`: what to run, against what, graded by which judge, gated how.

Paths in the file are relative to the file itself, so the harness behaves the
same whichever directory it is started from.
"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HttpTarget(Strict):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    """Values starting with `$` are read from the environment, e.g. `$TARGET_TOKEN`."""


class TargetConfig(Strict):
    name: str
    """What is under test, as it should appear in reports."""
    version: str = ""
    """The prompt, model or release being tested, e.g. `support-prompt-v7`."""
    adapter: str | None = None
    """`module.path:function`, an async function taking a Case and returning a Response."""
    http: HttpTarget | None = None

    @model_validator(mode="after")
    def one_kind(self) -> Self:
        if (self.adapter is None) == (self.http is None):
            raise ValueError("target needs exactly one of `adapter` or `http`")
        return self


class JudgeConfig(Strict):
    model: str
    """`provider:model` with an exact version, e.g. `anthropic:claude-sonnet-5`."""
    prompt: Path | None = None
    """Your own judge prompt. Defaults to the one shipped with the harness."""
    sources_dir: Path | None = None
    """Where `context_ref` files are read from when the target returns no sources."""
    max_source_chars: int = 20_000


class Price(Strict):
    input_per_mtok: float
    output_per_mtok: float


class GateConfig(Strict):
    baseline: Path | None = None
    """The report to compare with, usually the last release's."""
    tolerance: float = Field(default=0.02, ge=0, le=1)
    """How far a category's pass rate may drop below the baseline before the gate fails."""
    min_pass_rate: float = Field(default=0.0, ge=0, le=1)
    """A floor for the overall pass rate, whatever the baseline says."""


class Config(Strict):
    test_sets: list[Path]
    target: TargetConfig
    judge: JudgeConfig | None = None
    """Without a judge, rubric cases are reported as not graded."""
    concurrency: int = Field(default=4, ge=1)
    retries: int = Field(default=3, ge=0)
    timeout_seconds: float = Field(default=120, gt=0)
    prices: dict[str, Price] = Field(default_factory=dict)
    """USD per million tokens, keyed by the model name the target or judge reports."""
    gate: GateConfig = Field(default_factory=GateConfig)
    reports_dir: Path = Path("reports")
    path: Path = Path("evals.yaml")

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        config = cls.model_validate({**data, "path": path})
        return config.resolved()

    def resolved(self) -> "Config":
        base = self.path.parent

        def at(p: Path | None) -> Path | None:
            return None if p is None else (p if p.is_absolute() else base / p)

        judge = self.judge
        if judge is not None:
            judge = judge.model_copy(
                update={"prompt": at(judge.prompt), "sources_dir": at(judge.sources_dir)}
            )
        return self.model_copy(
            update={
                "test_sets": [at(p) for p in self.test_sets],
                "judge": judge,
                "gate": self.gate.model_copy(update={"baseline": at(self.gate.baseline)}),
                "reports_dir": at(self.reports_dir),
            }
        )
