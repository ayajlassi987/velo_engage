"""VE Measure — drift monitoring for the no-show/propensity score.

Computes the Population Stability Index (PSI) between a baseline window and
a current window of campaigns.noshow_score, using deciles cut from the
baseline distribution. Standard PSI thresholds: <0.1 stable, 0.1-0.25
moderate shift (watch), >=0.25 significant shift (retrain candidate).

There is no separate ve_measure HTTP endpoint to call this from (it's a pure
NATS subscriber — see services/ve_measure), and the console already holds
the query connection this needs, so the computation lives here rather than
behind a network hop.
"""

import math

PSI_WARNING_THRESHOLD = 0.1
PSI_CRITICAL_THRESHOLD = 0.25
MIN_BUCKET_SAMPLES = 10


def compute_psi(baseline_scores: list[float], current_scores: list[float], buckets: int = 10) -> dict:
    if len(baseline_scores) < buckets * MIN_BUCKET_SAMPLES or len(current_scores) < buckets * MIN_BUCKET_SAMPLES:
        return {
            "status": "insufficient_data", "psi": None,
            "baseline_n": len(baseline_scores), "current_n": len(current_scores),
        }

    sorted_baseline = sorted(baseline_scores)
    cut_points = [
        sorted_baseline[int(q * (len(sorted_baseline) - 1))]
        for q in (i / buckets for i in range(1, buckets))
    ]
    edges = [-math.inf, *cut_points, math.inf]

    def bucket_shares(scores: list[float]) -> list[float]:
        counts = [0] * buckets
        for score in scores:
            for i in range(buckets):
                if edges[i] <= score < edges[i + 1] or i == buckets - 1:
                    counts[i] += 1
                    break
        total = sum(counts) or 1
        return [count / total for count in counts]

    baseline_shares = bucket_shares(baseline_scores)
    current_shares = bucket_shares(current_scores)

    psi = 0.0
    for baseline_share, current_share in zip(baseline_shares, current_shares):
        # Floor each share so an empty bucket doesn't blow up log(0).
        b = max(baseline_share, 1e-4)
        c = max(current_share, 1e-4)
        psi += (c - b) * math.log(c / b)

    if psi < PSI_WARNING_THRESHOLD:
        status = "stable"
    elif psi < PSI_CRITICAL_THRESHOLD:
        status = "warning"
    else:
        status = "critical"

    return {
        "status": status,
        "psi": round(psi, 4),
        "baseline_n": len(baseline_scores),
        "current_n": len(current_scores),
        "buckets": buckets,
    }
