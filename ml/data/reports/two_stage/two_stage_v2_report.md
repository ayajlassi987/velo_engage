# Two-Stage v2 Training Report

## Data
- Rows: 110,000
- Split: train=77,000, val=16,500, test=16,500 (temporal 70/15/15)

## Stage Timing
- Stage 1 (booking): run at booking creation time.
- Stage 2 (pre-appointment): run as soon as reminder response is available (T-7 or T-3), and rerun at T-3 for final decision.

## Metrics (Test Set)
| stage | threshold | auc | pr_auc | brier | log_loss | accuracy | precision | recall | f1 | specificity | net_aed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| stage1_booking | 0.2500 | 0.7353 | 0.4900 | 0.1471 | 0.4598 | 0.7145 | 0.4014 | 0.5820 | 0.4751 | 0.7523 | 288720 |
| stage2_pre_appointment | 0.2700 | 0.7514 | 0.5336 | 0.1417 | 0.4466 | 0.7513 | 0.4508 | 0.5509 | 0.4959 | 0.8085 | 300880 |

## Confusion Matrix: Stage 1
|  | pred_show | pred_no_show |
| --- | --- | --- |
| actual_show | 9657 | 3180 |
| actual_no_show | 1531 | 2132 |

## Confusion Matrix: Stage 2
|  | pred_show | pred_no_show |
| --- | --- | --- |
| actual_show | 10379 | 2458 |
| actual_no_show | 1645 | 2018 |

## Recommended Production Flow
1. Score Stage 1 at booking for early intervention policy.
2. Score Stage 2 when first reminder response arrives (T-7 or T-3).
3. Always rerun Stage 2 at T-3 for final operational action.