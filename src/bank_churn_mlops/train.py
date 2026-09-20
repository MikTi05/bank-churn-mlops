"""Reproducibly train and save the Bank Churn classification pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from bank_churn_mlops.preprocess import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    TECHNICAL_COLUMNS,
    build_pipeline,
)

MODEL_VERSION = "1.0.0"
DEFAULT_RANDOM_STATE = 42
DEFAULT_TEST_SIZE = 0.2
DEFAULT_THRESHOLD = 0.5
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = PROJECT_ROOT / "Churn_Modelling.csv"
DEFAULT_ARTIFACT_PATH = PROJECT_ROOT / "artifacts" / "model.joblib"


def load_training_data(data_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load the source CSV and return raw ordered features and the binary target."""
    data = pd.read_csv(data_path)
    required_columns = set(FEATURE_COLUMNS + TECHNICAL_COLUMNS + [TARGET_COLUMN])
    missing_columns = sorted(required_columns.difference(data.columns))
    if missing_columns:
        raise ValueError(f"Dataset is missing required columns: {missing_columns}")

    unexpected_target_values = sorted(set(data[TARGET_COLUMN].dropna().unique()) - {0, 1})
    if unexpected_target_values or data[TARGET_COLUMN].isna().any():
        raise ValueError(
            f"{TARGET_COLUMN} must contain only 0 and 1 without missing values; "
            f"unexpected values: {unexpected_target_values}"
        )

    features = data.loc[:, FEATURE_COLUMNS].copy()
    target = data[TARGET_COLUMN].astype(int).copy()
    return features, target


def fit_pipeline(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
    test_size: float = DEFAULT_TEST_SIZE,
) -> tuple[Pipeline, dict[str, float | int]]:
    """Split data, fit only on the training partition, and evaluate on the holdout."""
    train_features, test_features, train_target, test_target = train_test_split(
        features,
        target,
        test_size=test_size,
        random_state=random_state,
        stratify=target,
    )

    pipeline = build_pipeline(random_state=random_state)
    pipeline.fit(train_features, train_target)

    probabilities = pipeline.predict_proba(test_features)[:, 1]
    predictions = (probabilities >= DEFAULT_THRESHOLD).astype(int)
    metrics: dict[str, float | int] = {
        "train_rows": len(train_features),
        "test_rows": len(test_features),
        "accuracy": float(accuracy_score(test_target, predictions)),
        "roc_auc": float(roc_auc_score(test_target, probabilities)),
    }
    return pipeline, metrics


def validate_artifact(artifact: Any, example: pd.DataFrame) -> float:
    """Validate the artifact contract and return one positive-class probability."""
    if not isinstance(artifact, dict) or set(artifact) != {"pipeline", "metadata"}:
        raise ValueError("Artifact must be a dict with exactly pipeline and metadata keys")

    metadata = artifact["metadata"]
    required_metadata = {"version", "features", "threshold"}
    missing_metadata = required_metadata.difference(metadata)
    if missing_metadata:
        raise ValueError(f"Artifact metadata is missing: {sorted(missing_metadata)}")
    if metadata["features"] != FEATURE_COLUMNS:
        raise ValueError("Artifact feature order does not match the training contract")

    probabilities = artifact["pipeline"].predict_proba(example.loc[:, FEATURE_COLUMNS])
    if probabilities.shape != (len(example), 2):
        raise ValueError(f"Unexpected predict_proba shape: {probabilities.shape}")
    if not np.isfinite(probabilities).all() or not ((0 <= probabilities) & (probabilities <= 1)).all():
        raise ValueError("predict_proba returned invalid probabilities")
    if not np.allclose(probabilities.sum(axis=1), 1.0):
        raise ValueError("Class probabilities do not sum to 1")
    return float(probabilities[0, 1])


def train_and_save(
    data_path: Path = DEFAULT_DATA_PATH,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
) -> tuple[dict[str, Any], dict[str, float | int]]:
    """Train the model, persist it, reload it, and validate the saved artifact."""
    features, target = load_training_data(data_path)
    pipeline, metrics = fit_pipeline(features, target)
    artifact = {
        "pipeline": pipeline,
        "metadata": {
            "version": MODEL_VERSION,
            "features": FEATURE_COLUMNS.copy(),
            "threshold": DEFAULT_THRESHOLD,
            "model": "LogisticRegression",
            "random_state": DEFAULT_RANDOM_STATE,
            "test_size": DEFAULT_TEST_SIZE,
        },
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    loaded_artifact = joblib.load(artifact_path)
    example_probability = validate_artifact(loaded_artifact, features.iloc[[0]])
    metrics["example_probability"] = example_probability
    return loaded_artifact, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact, metrics = train_and_save(args.data, args.output)
    summary = {
        "artifact": str(args.output.resolve()),
        "top_level_keys": list(artifact),
        "metadata": artifact["metadata"],
        "metrics": metrics,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

