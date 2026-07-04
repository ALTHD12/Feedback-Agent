"""
FeedbackCoachAgent — Pure LLM transform, no tools
===================================================
Agent B in the Feedback-Agent pipeline.

Design notes:
  - Intentionally tool-free. The Feedback Coach only needs to read text and
    produce text — it performs no external I/O. Keeping it tools-free makes
    it faster, cheaper, and easier to test in isolation.
  - Uses input_schema=FeedbackInput so that when wrapped as an AgentTool,
    the orchestrator LLM is given a clear function signature:
      feedback_coach(grade_output_json: str) → str
  - Output is plain prose (the student feedback letter), NOT structured JSON.
    The coach's output is the final student-facing artifact — not an
    intermediate data structure — so no output_schema is enforced.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.feedback_coach_prompt import FEEDBACK_COACH_SYSTEM_PROMPT
from schemas.grade_output import FeedbackInput
from google.adk.agents import Agent

feedback_coach = Agent(
    name="feedback_coach",
    description=(
        "Transforms a GradeOutput JSON into a personalised, actionable "
        "feedback letter for the student. "
        "Input: grade_output_json (the full GradeOutput JSON string from GradingAgent). "
        "Output: plain-text feedback letter. "
        "Does NOT re-grade or modify scores. No external tool calls."
    ),
    model="gemini-2.0-flash",
    instruction=FEEDBACK_COACH_SYSTEM_PROMPT,
    # ── Typed input schema ────────────────────────────────────────────────
    # When wrapped as AgentTool, ADK uses this schema to generate the tool's
    # callable signature. The orchestrator LLM receives a typed parameter list
    # rather than a free-form 'request' string.
    input_schema=FeedbackInput,
    # No output_schema — the feedback letter is free-form prose by design.
    # No tools — this agent performs zero external I/O.
)
