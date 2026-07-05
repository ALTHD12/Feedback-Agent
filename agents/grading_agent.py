"""
GradingAgent — LlmAgent with Pydantic output_schema + MCPToolset
================================================================
Agent A in the Feedback-Agent pipeline.

Key design decisions:
  - `output_schema=GradeOutput` enforces that the model's final response is
    valid JSON matching the GradeOutput Pydantic model. ADK handles the
    schema injection into the system prompt and validates the response before
    passing it downstream.
  - Tools (MCPToolset) and output_schema coexist: ADK exposes tools during
    the reasoning loop and only enforces structured output on the final reply.
  - `output_key="grade_output"` stores the result in session state so the
    orchestrator can read it without re-parsing.
"""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.grading_agent_prompt import GRADING_AGENT_SYSTEM_PROMPT
from schemas.grade_output import GradeOutput
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

_SERVER_SCRIPT = str(Path(__file__).parent.parent / "mcp_gradebook_server.py")

# ─── Toolset ─────────────────────────────────────────────────────────────────
# GradingAgent gets all 4 tools: get_rubric, get_submission,
# flag_for_review, submit_grade — as specified by GRADING_AGENT_SYSTEM_PROMPT.

def _make_grading_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[_SERVER_SCRIPT],
            )
        ),
        # Explicitly allow only the tools GradingAgent should call.
        # This prevents the agent from accidentally calling auditor-only tools.
        tool_filter=[
            "get_rubric",
            "get_submission",
            "flag_for_review",
        ],
    )


# ─── Agent definition ────────────────────────────────────────────────────────

grading_agent = Agent(
    name="grading_agent",
    description=(
        "Evaluates a single student submission against the rubric. "
        "Requires: student_id and assignment_id in the request. "
        "Calls get_rubric FIRST, then get_submission, optionally "
        "flag_for_review, then submit_grade. "
        "Returns a structured GradeOutput JSON."
    ),
    model="gemini-2.0-flash",
    instruction=GRADING_AGENT_SYSTEM_PROMPT,
    # ── Structured output ──────────────────────────────────────────────────
    # ADK injects GradeOutput's JSON schema into the model's system prompt and
    # validates that the final response parses as a valid GradeOutput.
    # This is the primary mechanism ensuring downstream agents get reliable JSON.
    output_schema=GradeOutput,
    # ── Session state key ─────────────────────────────────────────────────
    # The validated GradeOutput is stored at session.state["grade_output"]
    # so ConsistencyAuditorAgent and FeedbackCoachAgent can read it from state.
    output_key="grade_output",
    # ── Tools ─────────────────────────────────────────────────────────────
    tools=[_make_grading_toolset()],
)
