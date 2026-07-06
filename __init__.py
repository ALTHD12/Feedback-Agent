import sys
import importlib.util
from pathlib import Path

project_root = str(Path(__file__).parent.resolve())

# Load the actual agent.py module explicitly to bypass package naming conflicts
spec = importlib.util.spec_from_file_location("actual_agent_module", project_root + "/agent.py")
actual_agent = importlib.util.module_from_spec(spec)
sys.modules["actual_agent_module"] = actual_agent
spec.loader.exec_module(actual_agent)

# Expose as 'agent' for the ADK CLI evaluator
agent = actual_agent
