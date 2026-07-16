"""
Trains a multilingual intent classifier on the UAE/KSA WhatsApp intent dataset.
Covers 9 intents in English, Arabic MSA, and Arabic Gulf dialect.

Architecture: TF-IDF (char n-gram, handles Arabic morphology better than
word n-gram) + Logistic Regression. Fast to train, fast to serve, works
well on short WhatsApp messages. No GPU needed.

For higher accuracy on Arabic later: fine-tune CAMeL-BERT or AraBERT.
That's a Phase 2 upgrade; this ships something real today.
"""

import os
import pickle
import mlflow
import pandas as pd
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score, precision_recall_fscore_support
from sklearn.preprocessing import LabelEncoder

MLFLOW_URI   = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT   = "intent_classification"
MODEL_NAME   = "ve_intent_v1"
TRAIN_PATH   = "ml/data/intent/intent_train.csv"
VAL_PATH     = "ml/data/intent/intent_val.csv"
TEST_PATH    = "ml/data/intent/intent_test.csv"


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.dropna(subset=["text", "intent"])
    df["text"] = df["text"].astype(str).str.strip().str.lower()
    return df


def main():
    train = load(TRAIN_PATH)
    val   = load(VAL_PATH)
    test  = load(TEST_PATH)

    print(f"Train: {len(train)}  Val: {len(val)}  Test: {len(test)}")
    print(f"Intents: {sorted(train['intent'].unique())}")
    print(f"Languages: {train['language'].value_counts().to_dict()}")

    X_train = train["text"]
    y_train = train["intent"]
    X_test  = test["text"]
    y_test  = test["intent"]

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    with mlflow.start_run(run_name=MODEL_NAME):
        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                analyzer="char_wb",    # character n-grams — handles Arabic well
                ngram_range=(2, 5),    # bi-grams to 5-grams
                max_features=50_000,
                sublinear_tf=True,
                strip_accents=None,    # don't strip Arabic diacritics
            )),
            ("clf", LogisticRegression(
                C=5.0,
                max_iter=1000,
                class_weight="balanced",
                random_state=42,
                solver="lbfgs",
            )),
        ])

        pipeline.fit(X_train, y_train)

        # Evaluate
        y_pred  = pipeline.predict(X_test)
        y_proba = pipeline.predict_proba(X_test)
        acc     = accuracy_score(y_test, y_pred)
        # Macro-averaged, not micro/weighted — a 9-class intent classifier
        # should be judged on rare intents too (e.g. CANCEL_APPOINTMENT),
        # not dominated by whichever intent is most frequent in the dataset.
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test, y_pred, average="macro", zero_division=0
        )
        print(f"\nTest accuracy: {acc:.4f}  macro-P: {precision:.4f}  macro-R: {recall:.4f}  macro-F1: {f1:.4f}")
        print(classification_report(y_test, y_pred))

        # Per-language breakdown
        for lang in test["language"].unique():
            mask    = test["language"] == lang
            lang_df = test[mask]
            if len(lang_df) == 0: continue
            lang_preds = pipeline.predict(lang_df["text"])
            lang_acc   = accuracy_score(lang_df["intent"], lang_preds)
            print(f"  {lang}: {lang_acc:.3f} ({len(lang_df)} samples)")

        # Log to MLflow
        mlflow.log_params({
            "model_type":   "TF-IDF + LogisticRegression",
            "analyzer":     "char_wb",
            "ngram_range":  "(2,5)",
            "max_features": 50_000,
            "C":            5.0,
            "train_rows":   len(train),
            "training_data_path": TRAIN_PATH,
            "test_data_path": TEST_PATH,
            "class_balance": str(train["intent"].value_counts().to_dict()),
        })
        mlflow.log_metrics({
            "test_accuracy": acc,
            "test_precision_macro": precision,
            "test_recall_macro": recall,
            "test_f1_macro": f1,
        })

        # Save pipeline as pickle artifact (sklearn pipeline, not a deep model)
        model_path = "/tmp/intent_pipeline.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(pipeline, f)
        mlflow.log_artifact(model_path, artifact_path="model")
        mlflow.sklearn.log_model(pipeline, artifact_path="sklearn_model",
                                 registered_model_name=MODEL_NAME)

        print(f"\n✅  Intent model logged to MLflow as '{MODEL_NAME}'")


if __name__ == "__main__":
    main()