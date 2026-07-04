"""
Root Orchestrator Agent — Feedback-Agent Pipeline v2
=====================================================
This is the ADK entry point. ADK discovers `root_agent` at module level.

Architecture
────────────
The orchestrator uses the "agent-as-tool" pattern from the ADK travel planner
example: each specialist agent is wrapped in an AgentTool and exposed as a
callable function to the orchestrator LLM. The orchestrator decides WHEN and
in WHAT ORDER to invoke each specialist based on the conversation context.

  root_agent (LlmAgent — Orchestrator)
    ├── grade_submission_tool     = AgentTool(grading_agent)
    │     GradeOutput JSON; output_key="grade_output" in session state
    ├── generate_feedback_tool    = AgentTool(feedback_coach)
    │     Feedback letter (plain text)
    ├── audit_consistency_tool    = AgentTool(consistency_auditor)
    │     AuditResult JSON; output_key="audit_result" in session state
    └── flag_for_review_tool      = MCPToolset (flag_for_review ONLY)
          Called by orchestrator if audit_result.inconsistency_detected = True

Flow for a single submission:
  1. Orchestrator calls grade_submission_tool(student_id, assignment_id)
     → returns GradeOutput JSON
  2. Orchestrator calls generate_feedback_tool(grade_output_json=<JSON>)
     → returns feedback letter
  3. Orchestrator calls audit_consistency_tool(student_id, assignment_id,
     forward_grade_json=<JSON>)
     → returns AuditResult JSON
  4. Orchestrator reads AuditResult.inconsistency_detected:
       - If True  → calls flag_for_review_tool + returns final report with flag
       - If False → returns final report (grade + letter + audit clean)

Why AgentTool (not SequentialAgent):
  SequentialAgent is deprecated in ADK 2.3.0. The AgentTool pattern gives
  the orchestrator full conditional control: it can skip feedback for flagged
  submissions, retry grading, or short-circuit on errors — things a fixed
  sequential pipeline cannot do.

Why deterministic flagging:
  The orchestrator does NOT ask the LLM "should I flag this?" It reads
  `inconsistency_detected` from the AuditResult — a bool set by Python
  arithmetic in compute_score_divergence. This prevents the model from
  rationalising away real inconsistencies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ─── Import specialist agents ────────────────────────────────────────────────
from agents.grading_agent import grading_agent
from agents.feedback_coach import feedback_coach
from agents.consistency_auditor import consistency_auditor

# ─── ADK imports ─────────────────────────────────────────────────────────────
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_gradebook_server.py")

# ─── Orchestrator-level MCPToolset (flag_for_review only) ───────────────────
# The orchestrator calls flag_for_review directly when the auditor reports
# inconsistency_detected=True. This keeps flagging under orchestrator control —
# the auditor only detects; it does not flag.
def _make_flag_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[_SERVER_SCRIPT],
            )
        ),
        tool_filter=["flag_for_review"],
    )


# ─── Orchestrator system prompt ──────────────────────────────────────────────

ORCHESTRATOR_PROMPT = """
You are the Orchestrator of a multi-agent academic assessment pipeline.
You coordinate three specialist agents and make the final flagging decision.

═══════════════════════════════════════════════════════
AVAILABLE TOOLS
═══════════════════════════════════════════════════════

1. grade_submission(student_id, assignment_id)
   → Calls GradingAgent. Returns a GradeOutput JSON with per-criterion scores,
     total_score, flagged status, and flag_reasons.
   Call this FIRST for any grading request.

2. generate_feedback(grade_output_json)
   → Calls FeedbackCoachAgent. Transforms the GradeOutput JSON into a
     personalised feedback letter for the student.
   Call this SECOND, passing the full grade_output_json string.

3. audit_consistency(student_id, assignment_id, forward_grade_json)
   → Calls ConsistencyAuditorAgent. Re-grades with reversed criteria order,
     then runs a DETERMINISTIC Python diff (compute_score_divergence) to
     calculate exact per-criterion divergence numbers.
   Call this THIRD, passing the same student_id, assignment_id, and
   forward_grade_json (the GradeOutput JSON from step 1).

4. flag_for_review(student_id, assignment_id, reason)
   → Flags the submission for human review in the gradebook.
   Call this ONLY IF the AuditResult from step 3 contains
   "inconsistency_detected": true.
   Use reason="score_inconsistency" for divergence flags.

═══════════════════════════════════════════════════════
EXECUTION PROTOCOL
═══════════════════════════════════════════════════════

For each grading request, follow these steps IN ORDER:

STEP 1: Call grade_submission(student_id, assignment_id)
  Extract from the returned JSON:
    - grade_output_json  → save the full JSON string for steps 2 and 3
    - total_score        → include in final report
    - flagged            → if True, note the flag_reasons

STEP 2: Call generate_feedback(grade_output_json=<the full JSON from step 1>)
  EXCEPTION: If the GradeOutput.flag_reasons contains "suspected_plagiarism"
  OR "off_topic", SKIP this step (FeedbackCoach replaces the letter with a
  referral message; there is nothing useful to relay).

STEP 3: Call audit_consistency(
    student_id=<same>,
    assignment_id=<same>,
    forward_grade_json=<full JSON from step 1>
  )
  Read the returned AuditResult JSON and extract:
    - inconsistency_detected (bool) — SET BY DETERMINISTIC PYTHON CODE
    - max_abs_delta (int)
    - flagged_criteria (list)
    - auditor_verdict (string)

STEP 4: If inconsistency_detected=true →
    Call flag_for_review(student_id, assignment_id, reason="score_inconsistency")

═══════════════════════════════════════════════════════
FINAL REPORT FORMAT
═══════════════════════════════════════════════════════

After completing all steps, present a structured final report:

---
# Assessment Report — [assignment_title] — [student_id]

## Grade
Total: [total_score]/[max_score]
[table of per-criterion scores from GradeOutput.criteria_scores]
Flagged by Grading Agent: [Yes/No] — [flag_reasons if any]

## Feedback Letter
[The full text from generate_feedback]

## Consistency Audit
Max delta across criteria: [max_abs_delta] point(s)
Inconsistency detected: [Yes/No]
[if Yes] Flagged criteria: [list]
Auditor verdict: [auditor_verdict]
[if inconsistency_detected] ⚠️ Submission has been flagged for human review.

---

═══════════════════════════════════════════════════════
CRITICAL CONSTRAINTS
═══════════════════════════════════════════════════════

- You MUST call all three specialist tools for every submission.
- You MUST NOT infer inconsistency yourself — read inconsistency_detected
  from the AuditResult. This value was computed by Python, not by the LLM.
- You MUST NOT change or reinterpret scores from any specialist agent.
- If grade_submission or audit_consistency returns an error, report the error
  clearly and stop — do not fabricate scores.
"""


# ─── Root agent ──────────────────────────────────────────────────────────────

root_agent = Agent(
    name="feedback_agent_pipeline",
    description=(
        "End-to-end academic assessment pipeline. "
        "Grades a submission, generates personalised feedback, audits for "
        "grading consistency using deterministic score diffing, and flags "
        "if divergence exceeds threshold. "
        "Accepts: 'Grade student_id <id> on assignment <assignment_id>'"
    ),
    model="gemini-2.0-flash",
    instruction=ORCHESTRATOR_PROMPT,
    tools=[
        # ── AgentTools — sub-agents as callable tools ──────────────────
        # This is the ADK "agent-as-tool" pattern from the travel planner example.
        # The orchestrator LLM sees these as function calls with typed signatures.
        AgentTool(agent=grading_agent),
        AgentTool(agent=feedback_coach),
        AgentTool(agent=consistency_auditor),
        # ── Direct MCP tool — orchestrator-level flagging ──────────────
        _make_flag_toolset(),
    ],
)
