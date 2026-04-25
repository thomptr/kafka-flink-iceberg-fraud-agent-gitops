from kfp.dsl import component, Output, Dataset


@component(
    base_image="python:3.11-slim",
    packages_to_install=[
        "pyiceberg[pyarrow,s3]==0.7.1",
        "pandas==2.2.2",
        "pyarrow==15.0.2",
    ],
)
def data_ingestion(
    polaris_uri: str,
    warehouse: str,
    polaris_credential: str,
    minio_endpoint: str,
    minio_access_key: str,
    minio_secret_key: str,
    output_dataset: Output[Dataset],
) -> None:
    import os
    import pandas as pd
    from pyiceberg.catalog import load_catalog

    # Prefer env vars injected from k8s secret over explicit params
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", minio_access_key)
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", minio_secret_key)

    catalog = load_catalog(
        "polaris",
        type="rest",
        uri=polaris_uri,
        warehouse=warehouse,
        credential=polaris_credential,
        scope="PRINCIPAL_ROLE:ALL",
        **{
            "s3.endpoint": minio_endpoint,
            "s3.access-key-id": access_key,
            "s3.secret-access-key": secret_key,
            "s3.region": "us-east-1",
            "s3.path-style-access": "true",
            "client.region": "us-east-1",
        },
    )
    # Polaris with stsUnavailable=true cannot vend STS credentials.
    # Remove the delegation header so Polaris returns plain table metadata.
    catalog._session.headers.pop("X-Iceberg-Access-Delegation", None)
    table = catalog.load_table(("default", "transactions"))
    df = table.scan().to_pandas()

    # Label: top 5% by velocity OR top 5% by distance → ~10% fraud rate
    vel_threshold = df["amount_velocity_5min"].quantile(0.95)
    dist_threshold = df["distance_from_home_km"].quantile(0.95)
    df["label"] = (
        (df["amount_velocity_5min"] > vel_threshold) |
        (df["distance_from_home_km"] > dist_threshold)
    ).astype(int)

    df["transaction_time"] = pd.to_datetime(df["transaction_time"])

    # Dynamically include any coordinate columns present in the schema.
    # Common names vary by source system; include all candidates that exist.
    COORD_CANDIDATES = {
        "merchant_lat", "merchant_lon",
        "latitude", "longitude",
        "lat", "lon",
    }
    coord_cols = [c for c in df.columns if c.lower() in COORD_CANDIDATES]

    base_cols = ["user_id", "transaction_time", "amount",
                 "amount_velocity_5min", "distance_from_home_km", "label"]
    df = df[base_cols + coord_cols].dropna(subset=["amount", "label"])

    df.to_parquet(output_dataset.path, index=False)
    print(f"Ingested {len(df)} rows; fraud rate: {df['label'].mean():.3f}; "
          f"coord cols: {coord_cols or 'none'}")
