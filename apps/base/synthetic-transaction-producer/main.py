"""Async synthetic credit-card-style JSON events into Kafka (matches Flink SQL schema)."""

from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timezone

from aiohttp import web
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError
from faker import Faker

_fake = Faker()


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return v


def _build_record() -> dict:
    lat, lon = float(_fake.latitude()), float(_fake.longitude())
    return {
        "transaction_id": str(uuid.uuid4()),
        "user_id": random.randint(1, 50_000),
        "amount": round(random.uniform(1.0, 500.0), 2),
        "merchant": _fake.company(),
        "lat": lat,
        "lon": lon,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }


def _build_scored_record(overrides: dict) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "transaction_id": overrides.get("transaction_id", str(uuid.uuid4())),
        "user_id": int(overrides.get("user_id", random.randint(1, 50_000))),
        "amount": float(overrides.get("amount", round(random.uniform(100.0, 5000.0), 2))),
        "merchant": overrides.get("merchant", _fake.company()),
        "fraud_probability": float(overrides.get("fraud_probability", round(random.uniform(0.5, 0.99), 4))),
        "amount_velocity_5min": float(overrides.get("amount_velocity_5min", round(random.uniform(0.0, 10000.0), 2))),
        "distance_from_home_km": float(overrides.get("distance_from_home_km", round(random.uniform(0.0, 500.0), 2))),
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "processing_time": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }


class ProducerState:
    def __init__(self) -> None:
        self._paused = False
        self._lock = asyncio.Lock()

    async def is_paused(self) -> bool:
        async with self._lock:
            return self._paused

    async def set_paused(self, value: bool) -> None:
        async with self._lock:
            self._paused = value


def _auth_ok(request: web.Request) -> bool:
    token = os.environ.get("CONTROL_API_TOKEN", "").strip()
    if not token:
        return True
    want = f"Bearer {token}"
    return request.headers.get("Authorization", "") == want


def _need_auth_response() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


async def _handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _handle_status(request: web.Request) -> web.Response:
    state: ProducerState = request.app["state"]
    if not _auth_ok(request):
        return _need_auth_response()
    return web.json_response({"paused": await state.is_paused()})


async def _handle_pause(request: web.Request) -> web.Response:
    state: ProducerState = request.app["state"]
    if not _auth_ok(request):
        return _need_auth_response()
    await state.set_paused(True)
    return web.json_response({"paused": True})


async def _handle_resume(request: web.Request) -> web.Response:
    state: ProducerState = request.app["state"]
    if not _auth_ok(request):
        return _need_auth_response()
    await state.set_paused(False)
    return web.json_response({"paused": False})


async def _handle_inject(request: web.Request) -> web.Response:
    """POST /inject — publish one transaction to the transactions topic."""
    if not _auth_ok(request):
        return _need_auth_response()
    producer: AIOKafkaProducer | None = request.app.get("producer")
    if producer is None:
        return web.json_response({"error": "producer not ready"}, status=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = os.environ.get("KAFKA_TOPIC", "transactions")
    rec = _build_record()
    rec.update({k: v for k, v in body.items() if k in rec})
    await producer.send_and_wait(topic, value=rec, key=str(rec["user_id"]))
    return web.json_response({"injected": True, "topic": topic, "transaction_id": rec["transaction_id"]})


async def _handle_inject_scored(request: web.Request) -> web.Response:
    """POST /inject/scored — publish directly to scored-transactions topic, bypassing ML pipeline."""
    if not _auth_ok(request):
        return _need_auth_response()
    producer: AIOKafkaProducer | None = request.app.get("producer")
    if producer is None:
        return web.json_response({"error": "producer not ready"}, status=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    scored_topic = os.environ.get("KAFKA_SCORED_TOPIC", "scored-transactions")
    rec = _build_scored_record(body)
    await producer.send_and_wait(scored_topic, value=rec, key=str(rec["user_id"]))
    return web.json_response({"injected": True, "topic": scored_topic, "transaction_id": rec["transaction_id"]})


async def _run() -> None:
    state = ProducerState()
    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS")
    topic = os.environ.get("KAFKA_TOPIC", "transactions")
    rate = float(os.environ.get("EVENTS_PER_SEC", "10"))
    control_port = int(os.environ.get("CONTROL_PORT", "8080"))
    brokers = [b.strip() for b in bootstrap.split(",") if b.strip()]

    app = web.Application()
    app["state"] = state
    app["producer"] = None  # set after successful Kafka connect
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/status", _handle_status)
    app.router.add_post("/pause", _handle_pause)
    app.router.add_post("/resume", _handle_resume)
    app.router.add_post("/inject", _handle_inject)
    app.router.add_post("/inject/scored", _handle_inject_scored)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", control_port)
    await site.start()

    # Run Kafka connect + send loop in a background task so the aiohttp server keeps
    # serving /health while producer.start() retries (otherwise the event loop can stall
    # and probes see connection refused).

    async def kafka_loop() -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: str(k).encode("utf-8") if k is not None else None,
        )
        backoff_sec = float(os.environ.get("KAFKA_BOOTSTRAP_RETRY_DELAY_SEC", "3"))
        max_attempts = int(os.environ.get("KAFKA_BOOTSTRAP_MAX_ATTEMPTS", "40"))
        producer_started = False
        try:
            for _attempt in range(1, max_attempts + 1):
                try:
                    await producer.start()
                    producer_started = True
                    break
                except (KafkaConnectionError, OSError):
                    try:
                        await producer.stop()
                    except Exception:
                        pass
                    if _attempt >= max_attempts:
                        raise
                    await asyncio.sleep(backoff_sec)

            # Expose producer to inject handlers
            app["producer"] = producer

            interval = 1.0 / max(rate, 0.1)
            while True:
                if await state.is_paused():
                    await asyncio.sleep(0.25)
                    continue
                rec = _build_record()
                key = str(rec["user_id"])
                await producer.send_and_wait(topic, value=rec, key=key)
                await asyncio.sleep(interval)
        finally:
            app["producer"] = None
            if producer_started:
                try:
                    await producer.stop()
                except Exception:
                    pass

    asyncio.create_task(kafka_loop())
    await asyncio.sleep(float("inf"))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
