#!/bin/bash

# ==============================================================================
# Feedback Agent - Evaluation Suite Runner
# ==============================================================================
# This script runs the 5 core test cases against the multi-agent grading pipeline
# using the ADK agents-cli. Output is captured to the results/ directory.
# ==============================================================================

echo "=========================================================="
echo "🚀 Starting Feedback Agent Evaluation Suite"
echo "=========================================================="
echo ""

# Ensure results directory exists
mkdir -p results

PASSED=0
TOTAL=5

EVAL_FILES=(
  "evals/eval_01.json"
  "evals/eval_02.json"
  "evals/eval_03.json"
  "evals/eval_04.json"
  "evals/eval_05.json"
)

# Run each eval
for file in "${EVAL_FILES[@]}"; do
  # Extract filename without extension for logging
  filename=$(basename "$file")
  eval_id="${filename%.*}"
  
  # Extract the description from the JSON file for better terminal output
  # Using grep and sed since jq might not be installed, keeping dependencies low
  desc=$(grep '"description":' "$file" | sed -E 's/.*"description": "(.*)",/\1/')
  
  echo "▶ [$eval_id]"
  echo "  Test: $desc"
  
  # Run the ADK eval and capture output
  # (Output is routed to results folder so the terminal stays clean for the demo)
  agents-cli eval run "$file" > "results/${eval_id}_results.txt" 2>&1
  
  # Check exit status of the eval run (assuming ADK returns 0 on pass)
  if [ $? -eq 0 ]; then
    echo "  ✅ PASSED"
    PASSED=$((PASSED + 1))
  else
    echo "  ❌ FAILED"
    echo "     Check logs: results/${eval_id}_results.txt"
  fi
  echo ""
done

echo "=========================================================="
echo "📊 EVALUATION SUMMARY: $PASSED/$TOTAL evals passed"
echo "=========================================================="

# Exit with non-zero status if any tests failed
if [ $PASSED -ne $TOTAL ]; then
  exit 1
fi
exit 0
