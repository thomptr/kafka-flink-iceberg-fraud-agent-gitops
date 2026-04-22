from kfp.dsl import component, Input, Model


@component(
    base_image="python:3.11-slim",
    packages_to_install=["mlflow==2.13.0", "boto3==1.34.101"],
)
def register_model(
    trained_model: Input[Model],
    model_name: str,
    mlflow_tracking_uri: str,
    mlflow_s3_endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
) -> None:
    import os
    import mlflow
    from mlflow.tracking import MlflowClient

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
    os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient()

    model_uri = trained_model.metadata["model_uri"]
    mv = mlflow.register_model(model_uri=model_uri, name=model_name)

    client.transition_model_version_stage(
        name=model_name,
        version=mv.version,
        stage="Staging",
        archive_existing_versions=True,
    )
    print(f"Registered {model_name} v{mv.version} → Staging")
    print(f"Model URI: {model_uri}")
