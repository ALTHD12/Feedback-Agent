"""
run_pipeline.py — Batch-run all submissions end-to-end via ADK Runner
=====================================================================
Run from the project root:

    python run_pipeline.py [student_id...]

Examples:
    python run_pipeline.py                          # grades all 7 students
    python run_pipeline.py student_01 student_03    # grades specific students
    python run_pipeline.py --list                   # print available student IDs

Output is written to:
    data/run_results/<timestamp>/<student_id>.md    # markdown report per student
    data/grades.json                                # updated by MCP server
    data/flags.json                                 # updated by MCP server

Usage of ADK Runner (not adk web) so the full pipeline runs non-interactively.
"""

import asyncio
import json
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ─── Project root on sys.path ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ─── ADK Runner imports ───────────────────────────────────────────────────────
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# ─── Import root agent ────────────────────────────────────────────────────────
from agent import root_agent

# ─── Available students (from submissions_essay_01.json) ─────────────────────
CONTENT_DIR = PROJECT_ROOT / "content"
SUBMISSIONS_FILE = CONTENT_DIR / "submissions_essay_01.json"

def get_available_students() -> list[dict]:
    with open(SUBMISSIONS_FILE, "r", encoding="utf-8") as f:
        submissions = json.load(f)
    return [
        {
            "student_id": s["student_id"],
            "assignment_id": s["assignment_id"],
            "quality_label": s.get("quality_label", "unknown"),
            "expected_score_range": s.get("expected_score_range", "?"),
        }
        for s in submissions
    ]


# ─── ADK session runner ──────────────────────────────────────────────────────

async def run_one_student(
    student_id: str,
    assignment_id: str = "essay_01",
    output_dir: Path = None,
) -> str:
    """
    Runs the full pipeline for one student via ADK Runner.
    Returns the final text output of root_agent.
    """
    session_service = InMemorySessionService()

    runner = Runner(
        app_name="feedback_agent_pipeline",
        agent=root_agent,
        session_service=session_service,
    )

    user_id = f"batch_user_{student_id}"
    session = await session_service.create_session(
        app_name="feedback_agent_pipeline",
        user_id=user_id,
    )

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    f"Grade student_id={student_id} on assignment_id={assignment_id}. "
                    f"Run the full pipeline: grade, generate feedback, audit consistency, "
                    f"and flag if needed."
                )
            )
        ],
    )

    print(f"\n{'='*60}")
    print(f"  Processing: {student_id} / {assignment_id}")
    print(f"{'='*60}")

    full_output_parts = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    full_output_parts.append(part.text)
                    # Stream to console
                    print(part.text, end="", flush=True)

    print()  # newline after streaming output

    full_output = "".join(full_output_parts)

    # ── Save report ─────────────────────────────────────────────────────
    if output_dir and full_output.strip():
        report_path = output_dir / f"{student_id}.md"
        report_path.write_text(full_output, encoding="utf-8")
        print(f"  -> Saved to {report_path}")

    return full_output


async def run_batch(student_ids: list[str], assignment_id: str = "essay_01"):
    """Run the pipeline for multiple students sequentially."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "data" / "run_results" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    errors = {}

    for student_id in student_ids:
        try:
            output = await run_one_student(
                student_id=student_id,
                assignment_id=assignment_id,
                output_dir=output_dir,
            )
            results[student_id] = output
        except Exception as e:
            print(f"\n[ERROR] {student_id}: {e}")
            errors[student_id] = str(e)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE - {len(results)} succeeded, {len(errors)} failed")
    if errors:
        for sid, err in errors.items():
            print(f"  [FAIL] {sid}: {err}")
    print(f"  Reports: {output_dir}")
    print(f"  Grades:  {PROJECT_ROOT / 'data' / 'grades.json'}")
    print(f"  Flags:   {PROJECT_ROOT / 'data' / 'flags.json'}")
    print(f"{'='*60}")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch-run the Feedback-Agent pipeline on essay_01 submissions."
    )
    parser.add_argument(
        "students",
        nargs="*",
        help="Student IDs to grade. Omit to grade all available students.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available student IDs and exit.",
    )
    parser.add_argument(
        "--assignment",
        default="essay_01",
        help="Assignment ID (default: essay_01).",
    )
    args = parser.parse_args()

    available = get_available_students()

    if args.list:
        print("\nAvailable students:")
        for s in available:
            print(
                f"  {s['student_id']:<20} quality={s['quality_label']:<20} "
                f"expected={s['expected_score_range']}"
            )
        return

    if args.students:
        # Validate requested IDs
        available_ids = {s["student_id"] for s in available}
        for sid in args.students:
            if sid not in available_ids:
                print(f"[ERROR] Unknown student_id: '{sid}'. Use --list to see available.")
                sys.exit(1)
        target_students = args.students
    else:
        target_students = [s["student_id"] for s in available]

    print(f"\nFeedback-Agent Pipeline — Batch Run")
    print(f"Assignment : {args.assignment}")
    print(f"Students   : {', '.join(target_students)}")
    print(f"Model      : gemini-2.0-flash")

    asyncio.run(run_batch(target_students, args.assignment))


if __name__ == "__main__":
    main()
