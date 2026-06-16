"""Clustering quality metrics for the Lakshana discover benchmark."""

from __future__ import annotations

from collections import Counter


def clustering_metrics(pred_labels: list[int], true_labels: list[int]) -> dict:
    """ARI, NMI, V-measure, homogeneity, completeness, purity."""
    from sklearn.metrics import (
        adjusted_rand_score,
        completeness_score,
        homogeneity_score,
        normalized_mutual_info_score,
        v_measure_score,
    )

    n = len(pred_labels)
    assert n == len(true_labels), "Label count mismatch"

    ari = adjusted_rand_score(true_labels, pred_labels)
    nmi = normalized_mutual_info_score(true_labels, pred_labels)
    v_measure = v_measure_score(true_labels, pred_labels)
    homogeneity = homogeneity_score(true_labels, pred_labels)
    completeness = completeness_score(true_labels, pred_labels)

    total_correct = 0
    for cid in set(pred_labels):
        members = [true_labels[i] for i in range(n) if pred_labels[i] == cid]
        if members:
            total_correct += Counter(members).most_common(1)[0][1]
    purity = total_correct / n if n > 0 else 0

    return {
        "n_samples": n,
        "n_clusters_predicted": len(set(pred_labels)),
        "n_clusters_true": len(set(true_labels)),
        "adjusted_rand_index": round(ari, 4),
        "normalized_mutual_info": round(nmi, 4),
        "v_measure": round(v_measure, 4),
        "homogeneity": round(homogeneity, 4),
        "completeness": round(completeness, 4),
        "purity": round(purity, 4),
    }


def format_clustering_report(results: dict) -> str:
    """Render a clustering metrics dict as a readable table."""
    lines = ["=" * 70, "LAKSHANA DISCOVER BENCHMARK RESULTS", "=" * 70]
    lines.append(f"Documents:          {results['n_samples']}")
    lines.append(f"True clusters:      {results['n_clusters_true']}")
    lines.append(f"Predicted clusters: {results['n_clusters_predicted']}")
    lines.append("")
    lines.append(f"{'Metric':<30} {'Score':>10}")
    lines.append("-" * 42)
    for key in (
        "adjusted_rand_index",
        "normalized_mutual_info",
        "v_measure",
        "homogeneity",
        "completeness",
        "purity",
    ):
        label = key.replace("_", " ").title()
        lines.append(f"{label:<30} {results[key]:>10.4f}")
    return "\n".join(lines)
