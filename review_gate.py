import json
from datetime import datetime, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
REVIEW_QUEUE_FILE = DATA_DIR / "review_queue.json"

# Ensure data dir exists
DATA_DIR.mkdir(exist_ok=True)


def should_finalize(grade_output: dict, audit_output: dict) -> dict:
    """
    Decides whether a grade should be finalized automatically or held for human review.
    Checks flags, inconsistency markers, and severe grade deltas.
    """
    audit_summary = audit_output.get("audit_summary", {})
    
    # 1. Auditor found inconsistency in individual criteria scoring
    if audit_summary.get("inconsistency_detected"):
        return {"finalize": False, "reason": "auditor_score_inconsistency"}
        
    # 2. Auditor triggered a specific flag (e.g., missed flag, misquote)
    if audit_summary.get("flag_triggered"):
        return {"finalize": False, "reason": f"flag: {audit_summary.get('flag_reason')}"}
        
    # 3. Grading Agent flagged the submission (e.g., plagiarism, off-topic)
    if grade_output.get("flagged"):
        return {"finalize": False, "reason": f"grading_flag: {grade_output.get('flag_reasons')}"}
        
    # 4. Severe grade deflation (Auditor score much lower than Original)
    total_delta = audit_summary.get("total_delta", 0)
    if total_delta <= -3:
        return {"finalize": False, "reason": "significant_grade_deflation"}
        
    # 5. Severe grade inflation (Auditor score much higher than Original)
    if total_delta >= 3:
        return {"finalize": False, "reason": "significant_grade_inflation"}
        
    # Passed all automated checks
    return {"finalize": True, "reason": "passed_audit"}


def write_to_review_queue(student_id: str, assignment_id: str, reason: str, grade_output: dict, audit_output: dict):
    """
    Appends a flagged grade to the human review queue.
    """
    # Load existing queue
    queue_data = []
    if REVIEW_QUEUE_FILE.exists():
        with open(REVIEW_QUEUE_FILE, "r", encoding="utf-8") as f:
            try:
                queue_data = json.load(f)
            except json.JSONDecodeError:
                pass

    record = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "student_id": student_id,
        "assignment_id": assignment_id,
        "reason": reason,
        "original_grade": grade_output.get("total_score"),
        "auditor_grade": audit_output.get("audit_summary", {}).get("auditor_total"),
        "delta": audit_output.get("audit_summary", {}).get("total_delta"),
        "status": "pending_review",
        "reviewer_id": None,
        "reviewed_at": None,
        "final_decision": None
    }
    
    queue_data.append(record)
    
    # Write back to file
    with open(REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, indent=2, ensure_ascii=False)
        
    print(f"⚠️  Grade held for human review: {student_id} — {reason}")


def print_review_queue_summary():
    """
    Prints a summary table of the current review queue.
    """
    if not REVIEW_QUEUE_FILE.exists():
        print("Review queue is empty.")
        return
        
    with open(REVIEW_QUEUE_FILE, "r", encoding="utf-8") as f:
        try:
            queue_data = json.load(f)
        except json.JSONDecodeError:
            print("Review queue is empty or corrupted.")
            return
            
    pending = [item for item in queue_data if item.get("status") == "pending_review"]
    print(f"\nTotal items pending review: {len(pending)}")
    print("-" * 75)
    print(f"{'Student ID':<15} | {'Reason':<30} | {'Original':<8} | {'Auditor':<7} | {'Delta':<5}")
    print("-" * 75)
    
    reason_counts = {}
    for item in pending:
        sid = item.get("student_id", "N/A")
        reason = item.get("reason", "unknown")
        orig = item.get("original_grade", "N/A")
        aud = item.get("auditor_grade", "N/A")
        delta = item.get("delta", "N/A")
        
        # Format delta with explicit sign if integer
        if isinstance(delta, int) and delta > 0:
            delta_str = f"+{delta}"
        else:
            delta_str = str(delta)
            
        # Count reasons
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        # Print table row
        # Truncate reason if too long
        display_reason = (reason[:27] + "...") if len(reason) > 30 else reason
        print(f"{sid:<15} | {display_reason:<30} | {str(orig):<8} | {str(aud):<7} | {delta_str:<5}")
        
    print("-" * 75)
    print("\nPending items by reason:")
    for reason, count in reason_counts.items():
        print(f"  - {reason}: {count}")
    print()


# ---------------------------------------------------------------------------
# Demo Usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example outputs from agents
    grade_output_mock = {"flagged": False, "total_score": 14}
    audit_output_mock = {"audit_summary": {"inconsistency_detected": True, "flag_triggered": False, "auditor_total": 10, "total_delta": -4}}
    
    # 8 LINES OF DEMO USAGE
    gate_decision = should_finalize(grade_output_mock, audit_output_mock)
    if gate_decision["finalize"]:
        print("✅ Grade verified by Auditor. Releasing to student system.")
        # Proceed to notify student / write final grade to LMS...
    else:
        write_to_review_queue("student_02", "essay_01", gate_decision["reason"], grade_output_mock, audit_output_mock)
        # Next: A human reviewer logs into the dashboard, views review_queue.json,
        # reads Pass 2 alternative interpretations, and overrides or confirms the grade.
        
    print_review_queue_summary()
