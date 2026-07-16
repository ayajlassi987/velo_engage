# Temporal Leakage Strategy Comparison

## Experimental Setup
- Dataset size: 80,411
- Split: train=56,287, val=12,062, test=12,062 (temporal by row order)
- Target: `no_show`
- Booking features: 16
- Full features: 19

## Strategies
1. `solution_1_two_stage`: separate booking and pre-appointment models.
2. `solution_2_single_missingness`: one model with value+known encoding for post-action features.

## Stage-Level Metrics (train and test)
| approach | stage | split | threshold | auc | pr_auc | brier | ece | log_loss | precision | recall | f1 | specificity | accuracy | net_aed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| solution_1_two_stage | booking | train | 0.2300 | 0.7070 | 0.5008 | 0.1771 | 0.0193 | 0.5330 | 0.3743 | 0.7614 | 0.5018 | 0.5137 | 0.5822 | 1497360.0000 |
| solution_1_two_stage | booking | test | 0.2300 | 0.6695 | 0.4552 | 0.1838 | 0.0099 | 0.5506 | 0.3536 | 0.7245 | 0.4752 | 0.4936 | 0.5575 | 286620.0000 |
| solution_1_two_stage | pre_appointment | train | 0.2900 | 0.7599 | 0.5685 | 0.1641 | 0.0159 | 0.4990 | 0.4696 | 0.6669 | 0.5511 | 0.7122 | 0.6997 | 1592960.0000 |
| solution_1_two_stage | pre_appointment | test | 0.2900 | 0.7333 | 0.5420 | 0.1698 | 0.0127 | 0.5152 | 0.4497 | 0.6295 | 0.5246 | 0.7055 | 0.6845 | 312500.0000 |
| solution_2_single_missingness | booking | train | 0.2300 | 0.7087 | 0.5025 | 0.1767 | 0.0205 | 0.5323 | 0.3750 | 0.7662 | 0.5035 | 0.5122 | 0.5824 | 1509900.0000 |
| solution_2_single_missingness | booking | test | 0.2300 | 0.6702 | 0.4565 | 0.1836 | 0.0075 | 0.5502 | 0.3552 | 0.7284 | 0.4775 | 0.4945 | 0.5592 | 289750.0000 |
| solution_2_single_missingness | pre_appointment | train | 0.2800 | 0.7631 | 0.5738 | 0.1633 | 0.0189 | 0.4969 | 0.4620 | 0.6963 | 0.5555 | 0.6903 | 0.6920 | 1644230.0000 |
| solution_2_single_missingness | pre_appointment | test | 0.2800 | 0.7327 | 0.5419 | 0.1699 | 0.0138 | 0.5156 | 0.4403 | 0.6484 | 0.5244 | 0.6848 | 0.6748 | 316730.0000 |

## Aggregate Metrics (mean across booking and pre-appointment)
| approach | mean_auc | mean_pr_auc | mean_brier | mean_ece | mean_log_loss | mean_f1 | mean_precision | mean_recall | mean_net_aed | composite_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| solution_2_single_missingness | 0.7014 | 0.4992 | 0.1768 | 0.0106 | 0.5329 | 0.5010 | 0.3977 | 0.6884 | 303240.0000 | 6.9998 |
| solution_1_two_stage | 0.7014 | 0.4986 | 0.1768 | 0.0113 | 0.5329 | 0.4999 | 0.4016 | 0.6770 | 299560.0000 | 0.0000 |

## Recommendation
- Best approach by composite score: **solution_2_single_missingness**
- Use stage-level metrics for operational policy (booking vs pre-appointment) and aggregate metrics for architecture choice.