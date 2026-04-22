from kfp.dsl import component, Input, Output, Dataset, Model, Metrics


@component(
    base_image="python:3.11-slim",
    packages_to_install=[
        "xgboost==2.0.3",
        "scikit-learn==1.4.2",
        "pandas==2.2.2",
        "pyarrow==15.0.2",
        "mlflow==2.13.0",
        "boto3==1.34.101",
    ],
)
def train_model(
    input_dataset: Input[Dataset],
    mlflow_tracking_uri: str,
    experiment_name: str,
    mlflow_s3_endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    output_model: Output[Model],
    metrics: Output[Metrics],
) -> None:
    import os
    import mlflow
    import mlflow.xgboost
    import pandas as pd
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score, accuracy_score

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
    # Prefer env vars injected from k8s secret over explicit params
    os.environ.setdefault("AWS_ACCESS_KEY_ID", aws_access_key_id)
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", aws_secret_access_key)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow.set_experiment(experiment_name)

    df = pd.read_parquet(input_dataset.path)
    X = df[["amount", "amount_velocity_5min", "distance_from_home_km"]]
    y = df["label"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    mlflow.xgboost.autolog()
    with mlflow.start_run() as run:
        # Try GPU first; fall back to hist (CPU) if no CUDA device available
        try:
            import subprocess
            subprocess.run(["nvidia-smi"], check=True, capture_output=True)
            tree_method = "gpu_hist"
            device = "cuda"
        except Exception:
            tree_method = "hist"
            device = "cpu"

        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            tree_method=tree_method,
            device=device,
            eval_metric="auc",
            use_label_encoder=False,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_prob)
        acc = accuracy_score(y_test, y_pred)

        mlflow.log_metrics({"auc": auc, "accuracy": acc})
        mlflow.xgboost.log_model(model, artifact_path="xgboost-model")

        # KServe xgbserver v0.13.1 looks for .bst/.json/.ubj — not .xgb.
        # Log model.bst alongside the MLflow artifact so storage-initializer
        # downloads it and xgbserver can discover it.
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            bst_path = os.path.join(tmpdir, "model.bst")
            model.get_booster().save_model(bst_path)
            mlflow.log_artifact(bst_path, artifact_path="xgboost-model")

        model.save_model(output_model.path + ".json")
        output_model.metadata["run_id"] = run.info.run_id
        output_model.metadata["model_uri"] = f"runs:/{run.info.run_id}/xgboost-model"

        metrics.log_metric("auc", auc)
        metrics.log_metric("accuracy", acc)

        print(f"Run ID: {run.info.run_id}  AUC: {auc:.4f}  Accuracy: {acc:.4f}  device: {device}")
