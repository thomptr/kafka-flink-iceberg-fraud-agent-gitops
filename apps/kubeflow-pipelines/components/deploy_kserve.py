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
    import os
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
    model_uri = versions[0].source

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
                "model": {
                    "modelFormat": {"name": "xgboost"},
                    "storageUri": model_uri,
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {"cpu": "1", "memory": "1Gi"},
                    },
                }
            }
        },
    }

    k8s_config.load_incluster_config()
    custom_api = k8s_client.CustomObjectsApi()
    try:
        custom_api.create_namespaced_custom_object(
            group="serving.kserve.io",
            version="v1beta1",
            namespace=namespace,
            plural="inferenceservices",
            body=inference_service,
        )
        print(f"Created InferenceService {model_name} in {namespace}")
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
            print(f"Updated InferenceService {model_name} in {namespace}")
        else:
            raise
