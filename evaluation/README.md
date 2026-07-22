# Evaluation Module

This module provides a baseline and regression safety net for the existing Jira-to-test-case workflow.

It is intentionally isolated from production workflow routing and prompt execution logic.

## Dataset Layout

- evaluation/datasets/weclever_golden/dataset.json

The dataset is versioned and uses the schema in:

- evaluation/schemas/golden_dataset.py

## Run Evaluation

```powershell
python -m evaluation.run --dataset weclever_golden
python -m evaluation.run --dataset weclever_golden --ticket SAMPLE-001
python -m evaluation.run --dataset weclever_golden --deterministic
python -m evaluation.run --dataset weclever_golden --deterministic --compare-baseline --fail-on-regression
```

Reports are written to:

- reports/evaluation/<timestamp>/evaluation_report.json
- reports/evaluation/<timestamp>/evaluation_summary.md

Create a privacy-safe combined QA/evaluation report (counts, metrics, hashes and versions only):

```powershell
python -m evaluation.quality_report --evaluation-report reports/evaluation/<run>/evaluation_report.json --output reports/evaluation/quality_trends.json
```

## Compare Baseline vs Candidate

```powershell
python -m evaluation.compare --baseline <path-to-baseline-json> --candidate <path-to-candidate-json>
python -m evaluation.compare --baseline <path-to-baseline-json> --candidate <path-to-candidate-json> --thresholds evaluation/critical_thresholds.json --fail-on-regression
```

Comparisons can be labelled `baseline`, `prompt`, `model`, `retrieval`, or `ranking` and reports include dataset, prompt, component, and model identifiers. Live graph execution remains available; `--deterministic` is the credential-free CI mode.

## Controlled Golden Dataset Updates

Only tickets with an approved testcase review session may be added. The command redacts sensitive fields, anonymizes the ticket ID, creates a new immutable dataset snapshot, and appends reviewer/reason/hash metadata to the manifest. It never scans production tickets or trains a model.

```powershell
python -m evaluation.golden_cli --dataset weclever_golden --ticket PROJ-123 --expected-json reviewed_expectation.json --reviewed-by qa.lead --reason "Add reviewed payments example"
```

Updating an existing ticket also requires `--expectations-changed-reason`; prior snapshots are retained.

## Notes

- The runner executes existing graphs and nodes without altering routing.
- Evaluation reports are stored outside requirement workspaces.
- Synthetic fixture data intentionally avoids confidential production information.
- Aggregate QA feedback reports contain counts, rates, hashes, and version identifiers—not testcase or Jira body content.
