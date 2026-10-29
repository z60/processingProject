"""回归用例与评测结果。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegressionCase(BaseModel):
    case_id: str
    category: str
    input_text: str
    expected_status: str = ""
    expected_intent: str = ""
    assertions: list[dict] = Field(default_factory=list)
    turns: list[str] = Field(default_factory=list)
    source_version: str = ""


class CaseResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    status: str = ""
    intent: str = ""
    trigger_type: str = ""
    failures: list[str] = Field(default_factory=list)


class RegressionReport(BaseModel):
    total: int
    passed: int
    high_risk_total: int
    high_risk_missed: int
    pass_rate: float
    gate: str  # PASS | FAIL
    results: list[CaseResult] = Field(default_factory=list)
