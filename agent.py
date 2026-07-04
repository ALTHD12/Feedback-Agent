"""
ADK Multi-Agent Definition — Feedback-Agent System
===================================================
This file defines the Google ADK agent graph for the three-agent academic
assessment pipeline:

    Agent A — Grading Agent     (evaluates submission against rubric)
    Agent B — Feedback Coach    (turns grade output into a student letter)
    Agent C — Auditor Agent     (adversarial re-grade and inconsistency check)

All three agents share the same MCPToolset that wraps the real
mcp_gradebook_server.py subprocess over stdio.  The Auditor is wired as a
parallel peer alongside the Feedback Coach so both run after grading
completes.

ADK discovers this module because:
  - it lives at the project root (same directory as .env)
  - it exports a module-level `root_agent` variable

Usage:
    adk web          # interactive browser UI
    adk run          # interactive CLI
"""

import sys
from pathlib import Path

# Bring the agents/ prompt strings into scope
sys.path.insert(0, str(Path(__file__).parent))

from agents.grading_agent_prompt import GRADING_AGENT_SYSTEM_PROMPT
from agents.feedback_coach_prompt import FEEDBACK_COACH_SYSTEM_PROMPT
from agents.auditor_agent_prompt import AUDITOR_AGENT_SYSTEM_PROMPT

from google.adk.agents import Agent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

# ---------------------------------------------------------------------------
# MCP server subprocess parameters
# ---------------------------------------------------------------------------
# ADK will spawn   python <abs_path_to_mcp_gradebook_server.py>
# and communicate with it over stdin/stdout using the MCP stdio transport.
_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_gradebook_server.py")

_MCP_PARAMS = StdioConnectionParams(
    server_params=StdioServerParameters(
        command=sys.executable,          # same Python interpreter running ADK
        args=[_SERVER_SCRIPT],
        env=None,                        # inherit parent environment
    )
)

# ---------------------------------------------------------------------------
# Helper — one MCPToolset per agent
# ---------------------------------------------------------------------------
# ADK MCPToolset manages a connection lifecycle per agent session.
# Each agent gets its own toolset instance (they share the same server script
# but each will spawn/connect independently).

def _make_toolset() -> MCPToolset:
    """Return a fresh MCPToolset pointed at the gradebook MCP server."""
    return MCPToolset(connection_params=_MCP_PARAMS)


# ---------------------------------------------------------------------------
# Agent A — Grading Agent
# ---------------------------------------------------------------------------
grading_agent = Agent(
    name="grading_agent",
    description=(
        "Evaluates a single student submission against the rubric with "
        "precision and full transparency. Calls get_rubric, get_submission, "
        "optionally flag_for_review, then submit_grade. Outputs a "
        "<grade_output> JSON block."
    ),
    model="gemini-2.0-flash",
    instruction=GRADING_AGENT_SYSTEM_PROMPT,
    tools=[_make_toolset()],
)

# ---------------------------------------------------------------------------
# Agent B — Feedback Coach
# ---------------------------------------------------------------------------
feedback_coach = Agent(
    name="feedback_coach",
    description=(
        "Receives the <grade_output> JSON from the Grading Agent and "
        "transforms it into a personalised, actionable feedback letter "
        "addressed to the student. Does not re-grade or change scores."
    ),
    model="gemini-2.0-flash",
    instruction=FEEDBACK_COACH_SYSTEM_PROMPT,
    tools=[_make_toolset()],
)

# ---------------------------------------------------------------------------
# Agent C — Auditor Agent
# ---------------------------------------------------------------------------
auditor_agent = Agent(
    name="auditor_agent",
    description=(
        "Adversarial quality control agent. Independently re-grades the "
        "submission in reverse criterion order, compares against the Grading "
        "Agent's scores, and calls flag_for_review if inconsistencies are "
        "detected. Outputs an <audit_output> JSON block."
    ),
    model="gemini-2.0-flash",
    instruction=AUDITOR_AGENT_SYSTEM_PROMPT,
    tools=[_make_toolset()],
)

# ---------------------------------------------------------------------------
# Root agent — Sequential pipeline
# ---------------------------------------------------------------------------
# Flow:
#   1. grading_agent  → produces <grade_output>
#   2. feedback_coach → produces student feedback letter  (reads grade_output)
#   3. auditor_agent  → produces <audit_output>           (reads grade_output)
#
# SequentialAgent runs sub_agents in order, passing accumulated conversation
# context (including each agent's outputs) to the next agent.

root_agent = SequentialAgent(
    name="feedback_agent_pipeline",
    description=(
        "End-to-end academic assessment pipeline. "
        "Grades a student submission, generates personalised feedback, "
        "then audits the grade for consistency and bias."
    ),
    sub_agents=[grading_agent, feedback_coach, auditor_agent],
)
