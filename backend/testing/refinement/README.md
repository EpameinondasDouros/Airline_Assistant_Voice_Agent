# Refinement

This folder contains simple refinement helpers for testing artifacts.

Current first step:
- `review_test_run.py` loads one saved testing artifact
- a small Pydantic AI critic reviews tool usage and answer quality
- the result is returned as structured JSON

Example:

```bash
cd /Users/epameinondasdouros/Personal/TechMellon/Task-1/Airline_Assistant_Voice_Agent/backend
source .venv/bin/activate
python -m testing.refinement.review_test_run --artifact testing/outputs/<artifact>.json
```
