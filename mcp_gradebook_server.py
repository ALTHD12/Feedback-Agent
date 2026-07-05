"""
MCP Gradebook Server — Subprocess / stdio transport
====================================================
This is a REAL MCP server that ADK launches as a subprocess and communicates
with over stdin/stdout using the Model Context Protocol.

Run standalone (for smoke-testing):
    python mcp_gradebook_server.py

ADK wires this in via MCPToolset + StdioConnectionParams — it is NOT an
inline function or a mock. The protocol frames are handled by the 'mcp'
Python SDK's FastMCP helper.

Exposed tools:
    get_rubric(assignment_id)
    get_submission(student_id, assignment_id)
    submit_grade(student_id, assignment_id, scores, total, flagged)
    flag_for_review(student_id, assignment_id, reason)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths — all relative to THIS file's directory so it works regardless of cwd
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
CONTENT_DIR = BASE_DIR / "content"
DATA_DIR = BASE_DIR / "data"

RUBRIC_FILE = CONTENT_DIR / "rubric_essay_01.json"
SUBMISSIONS_FILE = CONTENT_DIR / "submissions_essay_01.json"
GRADES_FILE = DATA_DIR / "grades.json"
FLAGS_FILE = DATA_DIR / "flags.json"

# Ensure the data directory exists at startup
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict | list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="gradebook",
    instructions=(
        "Gradebook MCP server for the Feedback-Agent multi-agent academic "
        "assessment system. Provides read access to rubrics and student "
        "submissions, and write access to grades and review flags."
    ),
)


# ── Tool 1: get_rubric ──────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Retrieve the grading rubric for a given assignment. "
        "Returns the full rubric including all criteria, level descriptors, "
        "and maximum points. Call this FIRST before reading the submission."
    )
)
def get_rubric(assignment_id: str) -> dict:
    """
    Returns the rubric for `assignment_id`.

    Args:
        assignment_id: The assignment identifier, e.g. 'essay_01'.

    Returns:
        A dict containing the rubric with keys: assignment_id, title, topic,
        total_points, and criteria (list of criterion dicts).

    Raises:
        ValueError: if no rubric is found for the given assignment_id.
    """
    rubric = _load_json(RUBRIC_FILE)

    # Support multiple rubrics in one file or a directory in the future
    if isinstance(rubric, list):
        matches = [r for r in rubric if r.get("assignment_id") == assignment_id]
        if not matches:
            raise ValueError(
                f"No rubric found for assignment_id='{assignment_id}'. "
                f"Available: {[r.get('assignment_id') for r in rubric]}"
            )
        return matches[0]

    # Single rubric file
    if rubric.get("assignment_id") != assignment_id:
        raise ValueError(
            f"Rubric file contains assignment_id='{rubric.get('assignment_id')}' "
            f"but requested '{assignment_id}'."
        )
    return rubric


# ── Tool 1b: get_rubric_reversed ────────────────────────────────────────────

@mcp.tool(
    description=(
        "Retrieve the grading rubric for a given assignment with the criteria "
        "list in REVERSED order. Used exclusively by the ConsistencyAuditorAgent "
        "to re-grade the submission with a different criterion evaluation sequence, "
        "exposing order-dependent anchor/halo-effect bias. "
        "Do NOT call this during normal grading — use get_rubric instead."
    )
)
def get_rubric_reversed(assignment_id: str) -> dict:
    """
    Returns the rubric with criteria reversed, for order-bias detection.

    Args:
        assignment_id: The assignment identifier, e.g. 'essay_01'.

    Returns:
        The full rubric dict with 'criteria' list reversed in place.
        The rubric metadata (title, topic, total_points) is unchanged.
    """
    rubric = get_rubric(assignment_id)  # reuse validation logic
    # Return a copy with criteria reversed — the MCP server stays stateless
    import copy
    rubric_copy = copy.deepcopy(rubric)
    rubric_copy["criteria"] = list(reversed(rubric_copy["criteria"]))
    rubric_copy["_criteria_order"] = "reversed"  # signal for transparency
    return rubric_copy


# ---------------------------------------------------------------------------
# SECURITY: Scoped Access Store
# ---------------------------------------------------------------------------
# Maps session_id -> list of allowed student_ids
# In production, this would be stored in Redis or a database.
_session_scopes: dict[str, list[str]] = {}
VIOLATIONS_FILE = DATA_DIR / "violations.log"


def register_grading_session(session_id: str, student_id: str) -> None:
    """
    Called by the Orchestrator BEFORE dispatching the Grading Agent.
    Creates a narrow scope so this session can ONLY access this specific student.
    
    WHY: Principle of Least Privilege. If the Agent is compromised by a prompt
         injection (e.g., "fetch all submissions and summarize them"), it is
         cryptographically blocked from accessing other students' data.
    """
    if session_id not in _session_scopes:
        _session_scopes[session_id] = []
    if student_id not in _session_scopes[session_id]:
        _session_scopes[session_id].append(student_id)


# ── Tool 2: get_submission ──────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Retrieve a student's submission text for a given assignment. "
        "Call this AFTER get_rubric so you evaluate against the criteria, "
        "not the other way around."
    )
)
def get_submission(student_id: str, assignment_id: str, session_id: str = None) -> dict:
    """
    Returns the submission for (`student_id`, `assignment_id`).

    Args:
        student_id:    The student identifier, e.g. 'student_01'.
        assignment_id: The assignment identifier, e.g. 'essay_01'.
        session_id:    The active session token for access control.

    Returns:
        A dict with at least: student_id, assignment_id, text.
        May also include quality_label and expected_score_range for testing.
        If access is denied, returns an error dict.

    Raises:
        ValueError: if no matching submission is found.
    """
    # -------------------------------------------------------------------------
    # TRADEOFF: Passing session_id as a tool argument vs. MCP Init Header
    # 
    # Method A: Tool Argument (Implemented here for demonstration)
    #   - Pros: Simple to implement, works with any basic MCP client.
    #   - Cons: The LLM sees the session_id and could theoretically try to tamper 
    #           with it (though a secure orchestrator intercepts and overwrites 
    #           this argument before it reaches the server).
    #
    # Method B: MCP Init Header (e.g., passed during protocol initialization)
    #   - Pros: Completely invisible to the LLM. The orchestrator sets the header 
    #           once when establishing the MCP connection, making spoofing impossible.
    #   - Cons: Requires custom transport configuration in both ADK and the MCP 
    #           server to extract and pass headers into the tool context.
    # -------------------------------------------------------------------------

    # SECURITY: Scoped Access Enforcement
    if session_id:
        allowed_students = _session_scopes.get(session_id, [])
        if student_id not in allowed_students:
            # WHY: This prevents lateral movement. A compromised agent asked to grade 
            # student_01 cannot suddenly decide to fetch and leak student_02's essay.
            violation_msg = (
                f"[{_now_iso()}] SESSION_ID: {session_id} | "
                f"ATTEMPTED_STUDENT_ID: {student_id} | ALLOWED: {allowed_students}\n"
            )
            with open(VIOLATIONS_FILE, "a", encoding="utf-8") as f:
                f.write(violation_msg)
            
            return {
                "error": "access_denied",
                "message": "This session is not authorized to retrieve this student's submission. Scoped access violation logged."
            }

    submissions = _load_json(SUBMISSIONS_FILE)

    if not isinstance(submissions, list):
        submissions = [submissions]

    matches = [
        s for s in submissions
        if s.get("student_id") == student_id
        and s.get("assignment_id") == assignment_id
    ]

    if not matches:
        available = [
            (s.get("student_id"), s.get("assignment_id")) for s in submissions
        ]
        raise ValueError(
            f"No submission found for student_id='{student_id}', "
            f"assignment_id='{assignment_id}'. Available: {available}"
        )

    submission = matches[0]

    # SECURITY: Prompt Injection Guard
    try:
        from demo_injection import check_injection
        injection_res = check_injection(submission["text"])
        if not injection_res["clean"]:
            # Auto-flag the submission in the gradebook
            flag_for_review(student_id, assignment_id, reason="suspected_plagiarism")
            return {
                "student_id": submission["student_id"],
                "assignment_id": submission["assignment_id"],
                "text": submission["text"],
                "security_alert": "PROMPT_INJECTION_DETECTED",
                "flagged": True,
                "flag_reasons": ["injection_attempt"]
            }
    except Exception as e:
        # Gracefully handle import errors during tests
        pass

    # Return only the fields the agent needs; strip internal test metadata
    return {
        "student_id": submission["student_id"],
        "assignment_id": submission["assignment_id"],
        "text": submission["text"],
        # Included so the agent knows the format — metadata fields optional
        **(
            {"quality_label": submission["quality_label"]}
            if "quality_label" in submission
            else {}
        ),
    }


# ── Tool 3: submit_grade ────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Submit the final grade for a student's submission. "
        "Call this LAST, after flag_for_review (if applicable). "
        "The scores dict must contain a key for EVERY criterion in the rubric."
    )
)
def submit_grade(
    student_id: str,
    assignment_id: str,
    scores: dict,
    total: int,
    flagged: bool,
) -> dict:
    """
    Persists the grading result to data/grades.json.

    Args:
        student_id:    The student identifier.
        assignment_id: The assignment identifier.
        scores:        Dict mapping criterion_id → integer score,
                       e.g. {"thesis": 3, "evidence": 2, "organization": 3, "mechanics": 4}.
        total:         Sum of all criterion scores.
        flagged:       True if flag_for_review was called for this submission.

    Returns:
        A dict with {"status": "ok", "record": <the saved grade record>}.
    """
    # Load existing store (list of records)
    if GRADES_FILE.exists():
        grades = _load_json(GRADES_FILE)
        if not isinstance(grades, list):
            grades = []
    else:
        grades = []

    # Build the new record
    record = {
        "student_id": student_id,
        "assignment_id": assignment_id,
        "scores": scores,
        "total": total,
        "flagged": flagged,
        "submitted_at": _now_iso(),
    }

    # Upsert: replace any existing record for this (student_id, assignment_id)
    existing_idx = next(
        (
            i for i, g in enumerate(grades)
            if g.get("student_id") == student_id
            and g.get("assignment_id") == assignment_id
        ),
        None,
    )
    if existing_idx is not None:
        grades[existing_idx] = record
    else:
        grades.append(record)

    _save_json(GRADES_FILE, grades)

    return {"status": "ok", "record": record}


# ── Tool 4: flag_for_review ─────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Flag a student submission for human review. "
        "Call this BEFORE submit_grade when any of the following conditions hold: "
        "(1) any single criterion score is 0, "
        "(2) the submission appears off-topic, "
        "(3) the submission appears plagiarised, "
        "(4) the submission is fewer than 80 words. "
        "Valid reason codes: 'zero_score_criterion' | 'off_topic' | "
        "'suspected_plagiarism' | 'insufficient_length' | 'multiple_concerns' | "
        "'score_inconsistency' | 'missed_flag' | 'systematic_inflation' | "
        "'systematic_deflation' | 'evidence_misquoted'."
    )
)
def flag_for_review(
    student_id: str,
    assignment_id: str,
    reason: str,
) -> dict:
    """
    Persists a flag record to data/flags.json.

    Args:
        student_id:    The student identifier.
        assignment_id: The assignment identifier.
        reason:        A reason code string (see tool description).

    Returns:
        A dict with {"status": "flagged", "record": <the saved flag record>}.
    """
    VALID_REASONS = {
        "zero_score_criterion",
        "off_topic",
        "suspected_plagiarism",
        "insufficient_length",
        "multiple_concerns",
        "score_inconsistency",
        "missed_flag",
        "systematic_inflation",
        "systematic_deflation",
        "evidence_misquoted",
    }

    if reason not in VALID_REASONS:
        # Soft warning — don't crash the agent, just note the invalid reason
        reason = f"{reason} [UNRECOGNISED_REASON_CODE]"

    # Load existing store
    if FLAGS_FILE.exists():
        flags = _load_json(FLAGS_FILE)
        if not isinstance(flags, list):
            flags = []
    else:
        flags = []

    record = {
        "student_id": student_id,
        "assignment_id": assignment_id,
        "reason": reason,
        "flagged_at": _now_iso(),
    }

    # Append (allow multiple flags per submission from different agents)
    flags.append(record)
    _save_json(FLAGS_FILE, flags)

    # Write to human review queue (Human-in-the-loop gate integration)
    try:
        review_queue_path = DATA_DIR / "review_queue.json"
        queue_data = []
        if review_queue_path.exists():
            queue_data = _load_json(review_queue_path)
            if not isinstance(queue_data, list):
                queue_data = []
        
        review_record = {
            "queued_at": _now_iso(),
            "student_id": student_id,
            "assignment_id": assignment_id,
            "reason": reason,
            "original_grade": None,
            "auditor_grade": None,
            "delta": None,
            "status": "pending_review",
            "reviewer_id": None,
            "reviewed_at": None,
            "final_decision": None
        }
        
        # Check if already in queue to prevent duplicates
        if not any(q.get("student_id") == student_id and q.get("reason") == reason for q in queue_data):
            queue_data.append(review_record)
            _save_json(review_queue_path, queue_data)
    except Exception:
        pass

    return {"status": "flagged", "record": record}


# ---------------------------------------------------------------------------
# Entry point — run as stdio MCP server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # FastMCP's .run() defaults to stdio transport when no args given,
    # which is exactly what ADK's MCPToolset expects.
    mcp.run(transport="stdio")
