#!/bin/bash

# ==============================================================================
# Feedback Agent - Deployment Demo Walkthrough
# ==============================================================================

echo "=========================================================="
echo "Feedback Agent - Cloud Run Deployment Walkthrough"
echo "=========================================================="
echo ""

echo "▶ Step 1: Scaffolding for Cloud Run target"
sleep 1.5
echo "$ agents-cli scaffold enhance --deployment-target cloud_run"
echo ""
sleep 1.5

echo "▶ Step 2: Building container image"
sleep 1.5
echo "$ gcloud builds submit --tag gcr.io/<project>/grading-agent"
echo ""
sleep 1.5

echo "▶ Step 3: Deploying MCP server as Cloud Run service"
sleep 1.5
echo "$ gcloud run deploy mcp-gradebook --image gcr.io/<project>/mcp-server \\"
echo "       --platform managed --region us-central1 --allow-unauthenticated"
echo ""
sleep 1.5

echo "▶ Step 4: Deploying main grading agent"
sleep 1.5
echo "$ gcloud run deploy grading-agent --image gcr.io/<project>/grading-agent \\"
echo "       --set-env-vars MCP_SERVER_URL=https://mcp-gradebook-xxxx-uc.a.run.app"
echo ""
sleep 1.5

echo "▶ Step 5: Target architecture"
sleep 1.5
cat << "EOF"
  [Instructor] → [Cloud Run: Grading Agent]
                           ↓
                 [Cloud Run: MCP Server]
                           ↓
                 [Cloud Storage: Grade Store]
                           ↓
                 [Cloud Trace: Full audit trail]
EOF
echo ""
sleep 1.5
echo "In a live deploy, Cloud Trace captures every agent call, tool invocation, and flag event — giving instructors a full audit trail per student."
