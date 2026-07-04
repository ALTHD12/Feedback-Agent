"""
Pydantic schemas for the Feedback-Agent pipeline.

These are the canonical data contracts between agents:

  GradeOutput   — emitted by GradingAgent (enforced via output_schema)
  AuditResult   — emitted by ConsistencyAuditorAgent
  FeedbackInput — consumed by FeedbackCoachAgent (used as input_schema)

Using Pydantic here gives us:
  • Compile-time type safety across agent boundaries
  • ADK-level enforcement via output_schema (model must produce valid JSON)
  • Clean downstream parsing — no brittle regex on <grade_output> XML tags
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ─── GradeOutput ────────────────────────────────────────────────────────────

class CriterionScore(BaseModel):
    """Score and justification for a single rubric criterion."""
    criterion_id: str = Field(
        description="Rubric criterion identifier, e.g. 'thesis', 'evidence'."
    )
    criterion_name: str = Field(
        description="Human-readable criterion name, e.g. 'Thesis & Argument'."
    )
    evidence_quote: str = Field(
        description="Verbatim quote from the submission (max 50 words) that is most diagnostic for this criterion."
    )
    score: int = Field(
        ge=0, le=4,
        description="Integer score 0–4 for this criterion."
    )
    justification: str = Field(
        description="1–2 sentences citing the quote and explaining why this score was assigned."
    )


class GradeOutput(BaseModel):
    """
    Structured output produced by GradingAgent.

    This schema is enforced via ADK's output_schema field — the model MUST
    return valid JSON matching this structure before the turn completes.
    Downstream agents (FeedbackCoach, ConsistencyAuditor, Orchestrator) all
    consume this object directly, eliminating fragile XML-tag parsing.
    """
    student_id: str = Field(description="Student identifier.")
    assignment_id: str = Field(description="Assignment identifier.")
    assignment_title: str = Field(
        description="Title of the assignment from the rubric, e.g. 'Argumentative Essay'."
    )
    criteria_scores: List[CriterionScore] = Field(
        description="Ordered list of per-criterion scores covering every criterion in the rubric."
    )
    total_score: int = Field(
        ge=0,
        description="Sum of all criterion scores."
    )
    max_score: int = Field(
        default=16,
        description="Maximum possible total score (sum of all criterion max_points)."
    )
    flagged: bool = Field(
        description="True if flag_for_review was called for this submission."
    )
    flag_reasons: List[str] = Field(
        default_factory=list,
        description="List of flag reason codes. Empty list when flagged=False."
    )
    grading_notes: str = Field(
        default="",
        description="Optional notes for the auditor: anomalies, caveats, edge cases."
    )


# ─── AuditResult ────────────────────────────────────────────────────────────

class CriterionDiff(BaseModel):
    """Per-criterion comparison between forward-order and reverse-order grades."""
    criterion_id: str
    criterion_name: str
    forward_score: int = Field(description="Score from the original forward-order grading pass.")
    reverse_score: int = Field(description="Score from the reverse-order grading pass.")
    delta: int = Field(description="reverse_score - forward_score (can be negative).")
    abs_delta: int = Field(description="Absolute value of delta.")
    exceeds_threshold: bool = Field(
        description="True if abs_delta >= divergence_threshold."
    )


class AuditResult(BaseModel):
    """
    Output of ConsistencyAuditorAgent.

    Combines:
    - LLM reasoning: reverse-order re-grading of the submission
    - Deterministic code: `compute_score_divergence()` Python function that
      computes per-criterion absolute differences with zero LLM involvement.

    This is the ADK 2.0 'graph-based' pattern: weaving deterministic code
    with adaptive AI reasoning. The LLM cannot hallucinate the divergence
    numbers — they are computed by Python and passed back to the orchestrator
    as ground-truth integers.
    """
    student_id: str
    assignment_id: str
    divergence_threshold: int = Field(
        default=1,
        description="Maximum acceptable |delta| per criterion before flagging."
    )
    criteria_diffs: List[CriterionDiff] = Field(
        description="Per-criterion comparison computed by the deterministic diff tool."
    )
    max_abs_delta: int = Field(
        description="Highest absolute delta across all criteria (deterministic)."
    )
    inconsistency_detected: bool = Field(
        description="True if any criterion's abs_delta >= divergence_threshold (deterministic)."
    )
    auditor_verdict: str = Field(
        description="1–2 sentence LLM-authored assessment of whether the original grade is defensible."
    )
    potential_order_bias: bool = Field(
        description="True if divergence is concentrated in early criteria, suggesting halo-effect anchoring."
    )
    potential_order_bias_note: str = Field(
        default="",
        description="Explanation of which early criterion may have caused bias, if potential_order_bias=True."
    )


# ─── FeedbackInput ──────────────────────────────────────────────────────────

class FeedbackInput(BaseModel):
    """
    Input schema for FeedbackCoachAgent when called as an AgentTool.

    ADK's AgentTool uses input_schema to define the tool's callable signature.
    The orchestrator LLM passes these fields; AgentTool validates them and
    sends `grade_output_json` as the first user message to FeedbackCoachAgent.
    """
    grade_output_json: str = Field(
        description=(
            "The complete GradeOutput JSON string produced by GradingAgent. "
            "Pass the entire JSON, not a summary."
        )
    )


# ─── AuditInput ─────────────────────────────────────────────────────────────

class AuditInput(BaseModel):
    """
    Input schema for ConsistencyAuditorAgent when called as an AgentTool.
    """
    student_id: str = Field(description="Student identifier to re-grade.")
    assignment_id: str = Field(description="Assignment identifier to re-grade.")
    forward_grade_json: str = Field(
        description=(
            "The GradeOutput JSON from the original GradingAgent run. "
            "The auditor will compare its reverse-order scores against these."
        )
    )
