"""
ConsistencyAuditorAgent — Deterministic Code + Adaptive AI Reasoning
=====================================================================
Agent C in the Feedback-Agent pipeline.

╔══════════════════════════════════════════════════════════════════════════╗
║  ADK 2.0 "Graph-Based" Pattern: Weaving Deterministic Code with LLM    ║
╚══════════════════════════════════════════════════════════════════════════╝

This agent deliberately demonstrates the core ADK 2.0 architectural pitch:

  "Weave deterministic code with adaptive AI reasoning."
  — Google ADK documentation, 2026

Here's exactly how the weaving works:

  1. ADAPTIVE (LLM):  The auditor re-grades the submission with criteria in
     REVERSED order. Evaluating mechanics→organization→evidence→thesis instead
     of thesis→evidence→organization→mechanics tests whether the Grading Agent's
     scores are contaminated by "halo effects" — early-criterion impressions
     anchoring all subsequent scores upward or downward.

  2. DETERMINISTIC (Python): `compute_score_divergence()` is a pure Python
     function tool. It receives two score dicts and computes:
       - per-criterion absolute delta: |forward_score - reverse_score|
       - max_abs_delta across all criteria
       - a boolean flag per criterion (abs_delta >= threshold)
     No LLM is involved. The numbers are ground-truth Python arithmetic.
     The LLM CANNOT hallucinate these values — they are computed first, then
     passed back to the model as tool results.

  3. COMBINED VERDICT: The agent then authors `auditor_verdict` using BOTH
     its re-grading reasoning AND the deterministic diff numbers it received
     from the Python tool. The diff anchors the verdict in objective data.

Why this matters for judges:
  - A pure-LLM auditor could rate its own divergence as "acceptable" even
    when the numbers say otherwise. By computing divergence deterministically
    and injecting it back into context, we prevent the model from gaslighting
    itself about whether grading was consistent.
  - This is precisely the ADK pattern: use Python for anything that must be
    provably correct; use the LLM only for what requires language understanding.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.auditor_agent_prompt import AUDITOR_AGENT_SYSTEM_PROMPT
from schemas.grade_output import AuditResult, AuditInput
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

_SERVER_SCRIPT = str(Path(__file__).parent.parent / "mcp_gradebook_server.py")

# ─── Deterministic Python tool ──────────────────────────────────────────────

def compute_score_divergence(
    forward_scores_json: str,
    reverse_scores_json: str,
    threshold: int = 1,
) -> dict:
    """
    DETERMINISTIC divergence computation — no LLM involved.

    Computes per-criterion absolute differences between two score sets and
    identifies which criteria exceed the divergence threshold. This function
    is the "deterministic code" half of the ADK 2.0 graph-based pattern.

    Args:
        forward_scores_json: JSON string mapping criterion_id → score from
            the original forward-order grading run.
            Example: '{"thesis": 3, "evidence": 2, "organization": 3, "mechanics": 4}'
        reverse_scores_json: JSON string mapping criterion_id → score from
            the reverse-order re-grading run.
        threshold: Maximum acceptable absolute delta per criterion before the
            criterion is flagged as inconsistent. Default = 1.

    Returns:
        A dict with:
          - per_criterion: list of {criterion_id, forward, reverse, delta,
                                    abs_delta, exceeds_threshold}
          - max_abs_delta: int — highest abs_delta across all criteria
          - inconsistency_detected: bool — True if any criterion exceeds threshold
          - flagged_criteria: list of criterion_ids where abs_delta >= threshold
          - threshold_used: int — the threshold that was applied

    This return value is injected into the agent's context verbatim, giving
    the LLM concrete numbers to anchor its auditor_verdict.
    """
    try:
        forward: dict = json.loads(forward_scores_json)
        reverse: dict = json.loads(reverse_scores_json)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}

    all_ids = sorted(set(forward.keys()) | set(reverse.keys()))
    per_criterion = []
    flagged = []

    for cid in all_ids:
        f_score = forward.get(cid, 0)
        r_score = reverse.get(cid, 0)
        delta = r_score - f_score
        abs_delta = abs(delta)
        exceeds = abs_delta >= threshold

        per_criterion.append({
            "criterion_id": cid,
            "forward_score": f_score,
            "reverse_score": r_score,
            "delta": delta,
            "abs_delta": abs_delta,
            "exceeds_threshold": exceeds,
        })

        if exceeds:
            flagged.append(cid)

    max_abs_delta = max((c["abs_delta"] for c in per_criterion), default=0)

    return {
        "per_criterion": per_criterion,
        "max_abs_delta": max_abs_delta,
        "inconsistency_detected": len(flagged) > 0,
        "flagged_criteria": flagged,
        "threshold_used": threshold,
    }


# ─── Auditor system prompt extension ────────────────────────────────────────

_AUDITOR_EXTENDED_PROMPT = (
    AUDITOR_AGENT_SYSTEM_PROMPT.rstrip()
    + """

═══════════════════════════════════════════════════════
CONSISTENCY AUDIT PROTOCOL — TOOL SEQUENCE
═══════════════════════════════════════════════════════

You are the ConsistencyAuditorAgent. You MUST follow this exact tool sequence:

STEP 1 — Call get_rubric_reversed(assignment_id) to retrieve the rubric with
  criteria in reversed order. This is NOT a mistake — you must evaluate criteria
  in reverse order to test for halo-effect bias in the original grading.

STEP 2 — Call get_submission(student_id, assignment_id) to read the submission.

STEP 3 — Re-grade EVERY criterion independently using the reversed rubric order.
  Apply the same chain-of-thought (anchor → locate → quote → compare → assign).
  Your re-graded scores for this reversed pass = your "reverse_scores".

STEP 4 — Extract the forward scores from the forward_grade_json provided in your
  context. The forward_scores dict maps criterion_id → integer score.

STEP 5 — Call compute_score_divergence with:
    forward_scores_json = JSON of the forward scores (from forward_grade_json)
    reverse_scores_json = JSON of your reverse scores (from Step 3)
    threshold = 1
  This Python function computes the divergence deterministically. Read its
  output carefully — specifically: inconsistency_detected, max_abs_delta,
  flagged_criteria.

STEP 6 — Write your AuditResult output using the deterministic divergence numbers
  from Step 5. Do not invent divergence numbers — use exactly what the tool returned.
  Your auditor_verdict MUST reference specific criterion_ids and their deltas.

CRITICAL: Your output MUST be a valid AuditResult JSON object. The
inconsistency_detected and max_abs_delta fields MUST match what
compute_score_divergence returned — not your subjective impression.
"""
)


# ─── MCP toolset (read-only tools for auditor) ──────────────────────────────

def _make_auditor_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[_SERVER_SCRIPT],
            )
        ),
        # Auditor reads rubric (reversed) and submission — it does NOT call
        # submit_grade or flag_for_review (the orchestrator handles flagging).
        tool_filter=[
            "get_rubric_reversed",
            "get_submission",
        ],
    )


# ─── Agent definition ────────────────────────────────────────────────────────

consistency_auditor = Agent(
    name="consistency_auditor",
    description=(
        "Adversarial quality-control agent. Re-grades the submission with criteria "
        "in reversed order (to expose halo-effect bias), then calls the deterministic "
        "compute_score_divergence Python tool to produce provably-correct divergence numbers. "
        "Input: student_id, assignment_id, forward_grade_json (the original GradeOutput JSON). "
        "Returns AuditResult JSON with inconsistency_detected flag."
    ),
    model="gemini-2.0-flash",
    instruction=_AUDITOR_EXTENDED_PROMPT,
    # ── Typed input schema ────────────────────────────────────────────────
    input_schema=AuditInput,
    # ── Structured output ────────────────────────────────────────────────
    output_schema=AuditResult,
    output_key="audit_result",
    # ── Tools ─────────────────────────────────────────────────────────────
    # Two tool types coexist here — this IS the ADK graph-based pattern:
    #   1. MCPToolset  → adaptive (LLM-driven): fetch rubric + submission
    #   2. compute_score_divergence → deterministic (pure Python arithmetic)
    tools=[
        _make_auditor_toolset(),
        compute_score_divergence,   # ADK auto-wraps plain Python functions as FunctionTools
    ],
)
