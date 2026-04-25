from kfp.dsl import component, Input, Model


@component(
    base_image="python:3.11-slim",
    packages_to_install=["kubernetes==29.0.0", "mlflow==2.13.0", "boto3==1.34.101"],
)
def deploy_kserve(
    trained_model: Input[Model],
    model_name: str,
    namespace: str,
    mlflow_tracking_uri: str,
    mlflow_s3_endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
) -> None:
    import json
    import os
    import sys
    import mlflow
    from mlflow.tracking import MlflowClient
    from kubernetes import client as k8s_client, config as k8s_config

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
    os.environ.setdefault("AWS_ACCESS_KEY_ID", aws_access_key_id)
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", aws_secret_access_key)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    kf_client = MlflowClient()

    versions = kf_client.get_latest_versions(model_name, stages=["Staging"])
    if not versions:
        raise RuntimeError(f"No Staging version found for model '{model_name}'")
    source = versions[0].source
    # Convert MLFlow proxy URI to real S3 path for KServe storage-initializer.
    # mlflow-artifacts:/EXP/RUN/artifacts/... → s3://mlflow-artifacts/EXP/RUN/artifacts/...
    if source.startswith("mlflow-artifacts:/"):
        model_uri = "s3://mlflow-artifacts/" + source[len("mlflow-artifacts:/"):].lstrip("/")
    else:
        model_uri = source
    print(f"Model storage URI: {model_uri}", flush=True)

    k8s_config.load_incluster_config()
    v1_api = k8s_client.CoreV1Api()

    # Ensure the S3 secret exists so the storage-initializer can pull from MinIO.
    s3_secret_name = "kserve-s3-creds"
    s3_secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": s3_secret_name,
            "namespace": namespace,
            "annotations": {
                "serving.kserve.io/s3-endpoint": "minio.minio.svc.cluster.local:9000",
                "serving.kserve.io/s3-usehttps": "0",
                "serving.kserve.io/s3-region": "us-east-1",
                "serving.kserve.io/s3-useanoncredential": "false",
            },
        },
        "stringData": {
            "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", aws_access_key_id),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", aws_secret_access_key),
        },
    }
    try:
        v1_api.create_namespaced_secret(namespace=namespace, body=s3_secret)
        print(f"Created secret {s3_secret_name}", flush=True)
    except k8s_client.ApiException as e:
        if e.status == 409:
            v1_api.patch_namespaced_secret(
                name=s3_secret_name, namespace=namespace, body=s3_secret
            )
            print(f"Updated secret {s3_secret_name}", flush=True)
        else:
            raise

    # Ensure the ServiceAccount that references the S3 secret exists.
    sa_name = "kserve-sa"
    sa_body = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": sa_name, "namespace": namespace},
        "secrets": [{"name": s3_secret_name}],
    }
    try:
        v1_api.create_namespaced_service_account(namespace=namespace, body=sa_body)
        print(f"Created ServiceAccount {sa_name}", flush=True)
    except k8s_client.ApiException as e:
        if e.status != 409:
            raise

    inference_service = {
        "apiVersion": "serving.kserve.io/v1beta1",
        "kind": "InferenceService",
        "metadata": {
            "name": model_name,
            "namespace": namespace,
            "annotations": {"sidecar.istio.io/inject": "false"},
        },
        "spec": {
            "predictor": {
                "serviceAccountName": sa_name,
                "model": {
                    "modelFormat": {"name": "xgboost"},
                    "storageUri": model_uri,
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {"cpu": "1", "memory": "1Gi"},
                    },
                },
            }
        },
    }

    custom_api = k8s_client.CustomObjectsApi()
    try:
        custom_api.create_namespaced_custom_object(
            group="serving.kserve.io",
            version="v1beta1",
            namespace=namespace,
            plural="inferenceservices",
            body=inference_service,
        )
        print(f"Created InferenceService {model_name} in {namespace}", flush=True)
    except k8s_client.ApiException as e:
        if e.status == 409:
            custom_api.patch_namespaced_custom_object(
                group="serving.kserve.io",
                version="v1beta1",
                namespace=namespace,
                plural="inferenceservices",
                name=model_name,
                body=inference_service,
            )
            print(f"Updated InferenceService {model_name} in {namespace}", flush=True)
        else:
            raise
