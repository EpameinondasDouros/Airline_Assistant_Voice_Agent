# Refinement

This folder contains simple refinement helpers for testing artifacts.

Current flow:
- `review_test_run.py` loads one saved testing artifact
- a small Pydantic AI critic reviews tool usage and answer quality
- `analyze_root_cause.py` takes the same artifact and identifies the most likely root cause of failure
- both return structured JSON that can later drive automated refinement

Example:

```bash
cd /Users/epameinondasdouros/Personal/TechMellon/Task-1/Airline_Assistant_Voice_Agent/backend
source .venv/bin/activate
python -m testing.refinement.review_test_run --artifact testing/outputs/<artifact>.json
```

Then analyze the root cause:

```bash
python -m testing.refinement.analyze_root_cause --artifact testing/outputs/<artifact>.json
```
