# Academic report — LaTeX version

`main.tex` is a self-contained LaTeX conversion of `ACADEMIC_REPORT_DRAFT.md`
(repo root), styled after a teammate's PFE report from the same host
company (Velodoc) but built entirely around this project's own real,
verified architecture and implementation.

## Compiling

No TeX toolchain was available in the environment that produced this
file, so it has **not** been test-compiled. It only uses standard,
widely-available packages (`geometry`, `titlesec`, `fancyhdr`,
`booktabs`, `longtable`, `hyperref`, `underscore`, `amsmath`) and avoids
any institution-specific class file, so it should compile cleanly on
Overleaf or any reasonably current TeX Live / MiKTeX install:

```bash
pdflatex main.tex
pdflatex main.tex   # second pass for the table of contents / references
pdflatex main.tex   # third pass to let everything settle
```

Do a real compile and skim the log for warnings before treating the PDF
as final — the automated checks run while writing this file only
verified brace/environment balance and label/reference consistency, not
an actual TeX build.

## What still needs your input before submission

- **Front matter**: your name, university, program, defense date, and
  jury/supervisor names (all marked `TODO:` in `main.tex`'s preamble and
  title page). The industrial supervisors (Wael Hilali, Bilel Said) are
  pre-filled since they're a fact about the shared host company, not
  something you need to confirm.
- **Dedication / Acknowledgement**: personalize these two pages.
- **Figures**: every figure is a placeholder box with a text description
  of what it should show and where to source it from (the repo's own
  `ARCHITECTURE.md` diagram, real console screenshots, a Gantt-style
  planning chart). Replace each `\fbox{\parbox{...}}` block with a real
  `\includegraphics{...}`.
- **Chapter IV, Section "Other ranking models"**: this is deliberately
  left as a fill-in template, not populated with invented numbers — pull
  the real, current metrics for the propensity, expected-value, uplift,
  and survival models from your MLflow registry before submission.
- **Bibliography**: replace the placeholder/TODO entries with your own
  real citations.

## Where the real, verified numbers in Chapter IV came from

The no-show model's Chapter IV tables (feature distributions, feature
importance, the two-stage evaluation, and the encoding-strategy
comparison) are transcribed directly from this repository's own
artifacts, not invented:

- `ml/data/synthetic_no_show_uae_ksa_110k_summary_stats.csv`
- `ml/data/synthetic_no_show_uae_ksa_110k_catboost_feature_importance.csv`
- `ml/data/reports/two_stage/two_stage_v2_metrics.csv`
- `ml/data/reports/leakage/leakage_strategy_stage_metrics.csv`
- `ml/data/reports/leakage/leakage_strategy_aggregate_metrics.csv`

`ml/training/train_noshow_model.py`'s own docstring ("Train a CatBoost
no-show classifier on the 110k UAE/KSA synthetic dataset") and the git
history of the report CSVs above (authored by this project's own
repository owner) confirm these belong to this project, not to a
teammate's separate track.
