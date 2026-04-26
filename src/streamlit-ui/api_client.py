import os

import httpx
import streamlit as st

FRAUD_AGENT_BASE_URL = os.environ.get("FRAUD_AGENT_BASE_URL", "http://localhost:8000")
FRAUD_API_KEY = os.environ.get("FRAUD_API_KEY", "")
ANALYST_ID = os.environ.get("ANALYST_ID", "analyst")
ICEBERG_CATALOG_URI = os.environ.get("ICEBERG_CATALOG_URI", "")


class SessionConflictError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class FraudAgentClient:
    def __init__(
        self,
        base_url: str = FRAUD_AGENT_BASE_URL,
        api_key: str = FRAUD_API_KEY,
        analyst_id: str = ANALYST_ID,
    ):
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "X-API-Key": api_key,
            "X-Analyst-Id": analyst_id,
        }

    def _get(self, path: str, **kwargs) -> dict | list:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(f"{self.base_url}{path}", headers=self._headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{self.base_url}{path}", headers=self._headers, json=json or {})
            if resp.status_code == 409:
                raise SessionConflictError(resp.json().get("detail", "Conflict"))
            resp.raise_for_status()
            return resp.json()

    def list_alerts(self, status: str = "open,in_review") -> list[dict]:
        statuses = status.split(",")
        results = []
        for s in statuses:
            try:
                page = self._get("/api/v1/alerts", params={"status": s.strip(), "page_size": 100})
                results.extend(page.get("items", []))
            except Exception:
                pass
        return results

    def open_session(self, alert_id: str) -> dict:
        return self._post(f"/api/v1/alerts/{alert_id}/investigation-sessions")

    def run_investigation(self, transaction_id: str) -> dict:
        analyst_id = st.session_state.get("analyst_id", ANALYST_ID)
        return self._post("/api/v1/investigate", json={"transaction_id": transaction_id, "analyst_id": analyst_id})

    def get_session(self, session_id: str) -> dict:
        return self._get(f"/api/v1/investigation-sessions/{session_id}")

    def get_turns(self, session_id: str) -> list[dict]:
        return self._get(f"/api/v1/investigation-sessions/{session_id}/turns")

    def create_turn(self, session_id: str, question: str) -> dict:
        return self._post(
            f"/api/v1/investigation-sessions/{session_id}/turns",
            json={"question": question},
        )

    def conclude_session(self, session_id: str, outcome: str, notes: str | None = None) -> dict:
        return self._post(
            f"/api/v1/investigation-sessions/{session_id}/conclude",
            json={"outcome": outcome, "notes": notes},
        )

    def get_transaction_history(self, user_id: int, limit: int = 100) -> list[dict]:
        """Direct Iceberg query for raw transaction history (falls back gracefully)."""
        if not ICEBERG_CATALOG_URI:
            return []
        try:
            from pyiceberg.catalog.rest import RestCatalog
            catalog = RestCatalog(
                name="polaris",
                uri=ICEBERG_CATALOG_URI,
                warehouse=os.environ.get("ICEBERG_WAREHOUSE", "quickstart_catalog"),
            )
            table = catalog.load_table("fraud.transactions")
            scan = table.scan(row_filter=f"user_id = {user_id}", limit=limit)
            rows = []
            for batch in scan.to_arrow().to_batches():
                rows.extend(batch.to_pylist())
            return rows
        except Exception:
            return []
