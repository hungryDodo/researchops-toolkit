# Paradigm-aware peer review protocol

## Classify before reviewing

Use the paper's dominant evidence contract:

- **systems/implementation**: end-to-end benefit, realistic baselines, bottleneck attribution, overhead, scale, failure modes, reproducibility;
- **algorithm/method**: formal or mechanistic soundness, controlled comparisons, sensitivity, robustness, scope of generalization;
- **benchmark/evaluation**: construct validity, dataset/task coverage, leakage, metric choice, statistical reliability, benchmark incentives;
- **empirical analysis/measurement**: sampling, instrumentation validity, confounders, representativeness, causal restraint;
- **theory**: assumptions, proof correctness, necessity/novelty, relation between theorem and practical claim.

Mixed papers may need more than one lens, but do not apply every checklist indiscriminately.

## Severity

- `CRITICAL`: central claim unsupported/incorrect, invalid evaluation, fatal closest-work collision, or artifact cannot substantiate headline results;
- `MAJOR`: important missing control, attribution, baseline, robustness domain, or reproducibility detail that can change acceptance;
- `MINOR`: localized clarity, presentation, or bounded completeness issue.

Each finding states exact location, violated standard, evidence/attack path, likely consequence, and a concrete test or revision. Avoid generic “add more experiments.”

## Independence

Do not inherit the authors' conclusion as a premise. Verify central numbers and citations where feasible. A language rewrite is not a scientific fix. Track rebuttal risk separately from fixability.
