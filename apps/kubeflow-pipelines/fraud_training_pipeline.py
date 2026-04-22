import kfp
from kfp import dsl
from kfp.kubernetes import use_secret_as_env

from components.data_ingestion import data_ingestion
from components.train_model import train_model
from components.register_model import register_model
from components.deploy_kserve import deploy_kserve

POLARIS_URI = "http://polaris.polaris.svc.cluster.local:8181/api/catalog"
WAREHOUSE = "quickstart_catalog"
MINIO_ENDPOINT = "http://minio.minio.svc.cluster.local:9000"
MLFLOW_URI = "http://mlflow.mlflow.svc.cluster.local:5000"
KSERVE_NAMESPACE = "kubeflow-user-example-com"
MODEL_NAME = "fraud-detector"
EXPERIMENT_NAME = "fraud-detection"


@dsl.pipeline(
    name="fraud-training-pipeline",
    description="Train XGBoost fraud detector from Iceberg data, register in MLFlow, deploy to KServe",
)
def fraud_training_pipeline(
    polaris_uri: str = POLARIS_URI,
    warehouse: str = WAREHOUSE,
    minio_endpoint: str = MINIO_ENDPOINT,
    mlflow_tracking_uri: str = MLFLOW_URI,
    experiment_name: str = EXPERIMENT_NAME,
    model_name: str = MODEL_NAME,
    kserve_namespace: str = KSERVE_NAMESPACE,
):
    ingest_task = data_ingestion(
        polaris_uri=polaris_uri,
        warehouse=warehouse,
        polaris_credential="root:password",
        minio_endpoint=minio_endpoint,
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
    )
    ingest_task.set_caching_options(enable_caching=False)
    use_secret_as_env(
        ingest_task,
        secret_name="minio-flink-s3-credentials",
        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID", "rootPassword": "AWS_SECRET_ACCESS_KEY"},
    )

    train_task = train_model(
        input_dataset=ingest_task.outputs["output_dataset"],
        mlflow_tracking_uri=mlflow_tracking_uri,
        experiment_name=experiment_name,
        mlflow_s3_endpoint_url=minio_endpoint,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
    )
    use_secret_as_env(
        train_task,
        secret_name="minio-flink-s3-credentials",
        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID", "rootPassword": "AWS_SECRET_ACCESS_KEY"},
    )
    train_task.set_accelerator_type("nvidia.com/gpu").set_accelerator_limit(1)

    register_task = register_model(
        trained_model=train_task.outputs["output_model"],
        model_name=model_name,
        mlflow_tracking_uri=mlflow_tracking_uri,
        mlflow_s3_endpoint_url=minio_endpoint,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
    )
    use_secret_as_env(
        register_task,
        secret_name="minio-flink-s3-credentials",
        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID", "rootPassword": "AWS_SECRET_ACCESS_KEY"},
    )

    deploy_task = deploy_kserve(
        trained_model=train_task.outputs["output_model"],
        model_name=model_name,
        namespace=kserve_namespace,
        mlflow_tracking_uri=mlflow_tracking_uri,
        mlflow_s3_endpoint_url=minio_endpoint,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
    )
    use_secret_as_env(
        deploy_task,
        secret_name="minio-flink-s3-credentials",
        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID", "rootPassword": "AWS_SECRET_ACCESS_KEY"},
    )
    deploy_task.after(register_task)


if __name__ == "__main__":
    kfp.compiler.Compiler().compile(
        pipeline_func=fraud_training_pipeline,
        package_path="fraud_training_pipeline.yaml",
    )
    print("Compiled → fraud_training_pipeline.yaml")
