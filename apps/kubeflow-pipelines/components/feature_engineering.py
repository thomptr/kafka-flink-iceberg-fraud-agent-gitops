from kfp.dsl import component, Input, Output, Dataset


@component(
    base_image="python:3.11-slim",
    packages_to_install=["polars==0.20.16", "pyarrow==15.0.2", "numpy==1.26.4"],
)
def feature_engineering(
    input_dataset: Input[Dataset],
    output_dataset: Output[Dataset],
) -> None:
    import numpy as np
    import polars as pl

    df = pl.read_parquet(input_dataset.path)
    df = df.with_columns(pl.col("transaction_time").cast(pl.Datetime("us")))
    df = df.sort(["user_id", "transaction_time"])

    # --- 1. Rolling window aggregations (per user_id) ---
    # rolling_*_by uses transaction_time as the time axis; closed="right" includes
    # the current transaction in its own window (correct for burst-pattern detection).
    amount_windows = [("1h", "1h"), ("6h", "6h"), ("24h", "24h"), ("7d", "7d")]
    velocity_windows = [("1h", "1h"), ("24h", "24h")]

    # Temporary indicator column (1 per row) for counting transactions in window
    df = df.with_columns(pl.lit(1, dtype=pl.Float64).alias("_tx"))

    roll_exprs = []
    for win_name, win_dur in amount_windows:
        roll_exprs += [
            pl.col("amount")
              .rolling_mean_by("transaction_time", window_size=win_dur, min_periods=1, closed="right")
              .over("user_id")
              .alias(f"amount_avg_{win_name}"),
            pl.col("amount")
              .rolling_max_by("transaction_time", window_size=win_dur, min_periods=1, closed="right")
              .over("user_id")
              .alias(f"amount_max_{win_name}"),
            pl.col("amount")
              .rolling_min_by("transaction_time", window_size=win_dur, min_periods=1, closed="right")
              .over("user_id")
              .alias(f"amount_min_{win_name}"),
        ]
    for win_name, win_dur in velocity_windows:
        roll_exprs.append(
            pl.col("_tx")
              .rolling_sum_by("transaction_time", window_size=win_dur, min_periods=1, closed="right")
              .over("user_id")
              .alias(f"tx_count_{win_name}")
        )
    # Rolling 24h avg distance from home — user's typical geographic radius
    roll_exprs.append(
        pl.col("distance_from_home_km")
          .rolling_mean_by("transaction_time", window_size="24h", min_periods=1, closed="right")
          .over("user_id")
          .alias("avg_distance_from_home_24h")
    )
    df = df.with_columns(roll_exprs).drop("_tx")

    # --- 2. Time-based / cyclic features ---
    df = df.with_columns([
        pl.col("transaction_time").dt.hour().alias("hour_of_day"),
        # Polars dt.weekday(): Mon=1…Sun=7; subtract 1 → Mon=0…Sun=6 (Pandas convention)
        (pl.col("transaction_time").dt.weekday() - 1).alias("day_of_week"),
    ])
    df = df.with_columns([
        (pl.col("day_of_week") >= 5).cast(pl.Int8).alias("is_weekend"),
        (pl.col("hour_of_day") < 6).cast(pl.Int8).alias("is_night"),
    ])
    # Cyclic encoding via numpy arrays — vectorised, no per-row UDF overhead
    hour_arr = df["hour_of_day"].to_numpy().astype(np.float64)
    dow_arr  = df["day_of_week"].to_numpy().astype(np.float64)
    df = df.with_columns([
        pl.Series("hour_sin", np.sin(2 * np.pi * hour_arr / 24)),
        pl.Series("hour_cos", np.cos(2 * np.pi * hour_arr / 24)),
        pl.Series("dow_sin",  np.sin(2 * np.pi * dow_arr  / 7)),
        pl.Series("dow_cos",  np.cos(2 * np.pi * dow_arr  / 7)),
    ])

    # --- 3. Time since last transaction per user ---
    # -1 sentinel for a user's first transaction in this batch (no prior history)
    df = df.with_columns(
        (
            pl.col("transaction_time")
            - pl.col("transaction_time").shift(1).over("user_id")
        )
        .dt.total_seconds()
        .fill_null(-1)
        .alias("seconds_since_last_tx")
    )

    # --- 4. Geospatial / risk features ---
    # Requires lat/lon columns in the Parquet; degrade gracefully if absent.
    lat_col = next(
        (c for c in df.columns if c.lower() in
         ("merchant_lat", "lat", "latitude", "merchant_latitude")), None
    )
    lon_col = next(
        (c for c in df.columns if c.lower() in
         ("merchant_lon", "lon", "longitude", "merchant_longitude")), None
    )

    if lat_col and lon_col:
        df = df.with_columns([
            pl.col(lat_col).shift(1).over("user_id").alias("_prev_lat"),
            pl.col(lon_col).shift(1).over("user_id").alias("_prev_lon"),
        ])
        curr_lat = df[lat_col].to_numpy()
        curr_lon = df[lon_col].to_numpy()
        prev_lat = df["_prev_lat"].to_numpy()
        prev_lon = df["_prev_lon"].to_numpy()

        has_prev = ~np.isnan(prev_lat)
        dist = np.full(len(df), -1.0)
        if has_prev.any():
            R    = 6371.0
            la1  = np.radians(curr_lat[has_prev])
            la2  = np.radians(prev_lat[has_prev])
            d_la = np.radians(prev_lat[has_prev] - curr_lat[has_prev])
            d_lo = np.radians(prev_lon[has_prev] - curr_lon[has_prev])
            a    = (np.sin(d_la / 2) ** 2
                    + np.cos(la1) * np.cos(la2) * np.sin(d_lo / 2) ** 2)
            dist[has_prev] = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        speed = np.full(len(df), -1.0)
        secs  = df["seconds_since_last_tx"].to_numpy()
        valid = (dist >= 0) & (secs > 0)
        if valid.any():
            speed[valid] = dist[valid] / (secs[valid] / 3600.0)

        df = df.with_columns([
            pl.Series("distance_from_last_location_km", dist),
            pl.Series("speed_km_per_hour", speed),
            pl.Series("is_impossible_travel", (speed > 900).astype(np.int8)),
        ]).drop(["_prev_lat", "_prev_lon"])
    else:
        print("WARNING: No coordinate columns found; geospatial features set to sentinel -1 / 0")
        df = df.with_columns([
            pl.lit(-1.0).alias("distance_from_last_location_km"),
            pl.lit(-1.0).alias("speed_km_per_hour"),
            pl.lit(0).cast(pl.Int8).alias("is_impossible_travel"),
        ])

    df.write_parquet(output_dataset.path)

    temporal_cols = [
        "hour_of_day", "day_of_week", "is_weekend", "is_night",
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "seconds_since_last_tx",
    ]
    rolling_cols = [c for c in df.columns if any(c.startswith(p) for p in
                    ("amount_avg_", "amount_max_", "amount_min_", "tx_count_"))]
    geo_cols = ["distance_from_last_location_km", "speed_km_per_hour",
                "is_impossible_travel", "avg_distance_from_home_24h"]
    print(
        f"Feature engineering complete: {len(df)} rows — "
        f"{len(rolling_cols)} rolling, {len(temporal_cols)} temporal, {len(geo_cols)} geo"
    )
