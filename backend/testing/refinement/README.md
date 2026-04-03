# Refinement

This folder contains simple refinement helpers for testing artifacts.

Current flow:
- `review_test_run.py` loads one saved testing artifact
- a small Pydantic AI critic reviews tool usage and answer quality
- `analyze_root_cause.py` takes the same artifact and identifies the most likely root cause of failure
- `generate_fix_plan.py` creates a bounded-section fix plan
- `apply_fix_plan.py` applies the bounded edits, runs sync if needed, reruns validation, and updates the report
- `run_refinement_cycle.py` runs the full loop in one command

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

Generate a bounded fix plan:

```bash
python -m testing.refinement.generate_fix_plan --artifact testing/outputs/<artifact>.json
```

Apply a generated plan report:

```bash
python -m testing.refinement.apply_fix_plan testing/refinement/reports/<report>.json
```

Or run the whole loop:

```bash
python -m testing.refinement.run_refinement_cycle --artifact testing/outputs/<artifact>.json --apply
```
