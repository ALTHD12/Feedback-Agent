# Feedback-Agent

A multi-agent academic assessment system built with **Google ADK** and a **real MCP server**.

## Architecture

```
ADK Web UI  (http://localhost:8000)
  │
  ├─ grading_agent   ──┐
  ├─ feedback_coach  ──┤ MCPToolset (stdio subprocess)
  └─ auditor_agent   ──┘
                        │
               mcp_gradebook_server.py
               (separate Python process — real MCP stdio server)
```

The MCP server exposes 4 tools:

| Tool | Description |
|---|---|
| `get_rubric(assignment_id)` | Returns the full rubric criteria |
| `get_submission(student_id, assignment_id)` | Returns submission text |
| `submit_grade(student_id, assignment_id, scores, total, flagged)` | Writes to `data/grades.json` |
| `flag_for_review(student_id, assignment_id, reason)` | Writes to `data/flags.json` |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
copy .env.example .env
# then edit .env and replace your_google_api_key_here
```

### 3. Smoke-test the MCP server

```bash
python mcp_gradebook_server.py
# Should start without errors (press Ctrl+C to stop)
```

### 4. Launch ADK Web

```bash
adk web
```

Open **http://localhost:8000** in your browser.

Select `feedback_agent_pipeline` and send a message like:

```
Grade student_01's submission for assignment essay_01.
```

The pipeline will:
1. **Grading Agent** → calls `get_rubric` + `get_submission` → outputs `<grade_output>` JSON
2. **Feedback Coach** → reads `<grade_output>` → writes the student feedback letter
3. **Auditor Agent** → re-grades in reverse order → outputs `<audit_output>` JSON

Check `data/grades.json` and `data/flags.json` for persisted results.

## Project Structure

```
Feedback-Agent/
├── agents/                        # System prompts (Agent A, B, C)
│   ├── grading_agent_prompt.py
│   ├── feedback_coach_prompt.py
│   └── auditor_agent_prompt.py
├── content/                       # Seed data
│   ├── rubric_essay_01.json
│   └── submissions_essay_01.json
├── data/                          # Runtime output (created automatically)
│   ├── grades.json
│   └── flags.json
├── mcp_gradebook_server.py        # MCP stdio server (subprocess)
├── agent.py                       # ADK agent graph (root_agent)
├── requirements.txt
├── .env.example
└── README.md
```

## Students available for grading

| student_id | Quality | Expected score |
|---|---|---|
| `student_01` | Strong | 14–16 |
| `student_02` | Strong | 13–15 |
| `student_03` | Weak | 1–4 |
| `student_04` | Weak | 0–3 |
| `student_05` | Borderline | 7–10 |
| `student_06` | Borderline | 8–11 |
| `trap_student` | Auditor trap (order-bias test) | varies |
