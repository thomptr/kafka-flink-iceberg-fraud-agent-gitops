import time
from typing import Any
from uuid import UUID

import structlog
from langchain_core.callbacks.base import BaseCallbackHandler
from opentelemetry import context, trace
from opentelemetry.trace import SpanKind, StatusCode

from app.tracing import get_tracer

log = structlog.get_logger(__name__)


class FraudGraphTraceCallback(BaseCallbackHandler):
    def __init__(self, alert_id: str) -> None:
        super().__init__()
        self.alert_id = alert_id
        self._node_times: dict[UUID, float] = {}
        self._tool_times: dict[UUID, float] = {}
        self._llm_times: dict[UUID, float] = {}
        self._span_stack: dict[UUID, Any] = {}

        self._tracer = get_tracer("fraud-alert-agent.langgraph")
        self._root_span = self._tracer.start_span(
            "investigation",
            kind=SpanKind.INTERNAL,
            attributes={"investigation.alert_id": self.alert_id},
        )
        self._root_token = context.attach(
            trace.set_span_in_context(self._root_span)
        )

    # --- Node (chain) callbacks ---

    def on_chain_start(self, serialized: dict, inputs: dict, *, run_id: UUID, **kwargs: Any) -> None:
        name = serialized.get("name", "unknown")
        self._node_times[run_id] = time.monotonic()
        self._span_stack[run_id] = self._tracer.start_span(
            f"node.{name}",
            attributes={"alert_id": self.alert_id},
        )
        log.debug("node_start", event="node_start", node_name=name, run_id=str(run_id), alert_id=self.alert_id)

    def on_chain_end(self, outputs: dict, *, run_id: UUID, **kwargs: Any) -> None:
        t0 = self._node_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - t0) * 1000) if t0 is not None else 0
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_attribute("duration_ms", duration_ms)
            span.set_status(StatusCode.OK)
            span.end()
        node_name = kwargs.get("name", "unknown")
        log.info("node_end", event="node_end", node_name=node_name, run_id=str(run_id), alert_id=self.alert_id, duration_ms=duration_ms)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_status(StatusCode.ERROR, str(error))
            span.end()
        self._node_times.pop(run_id, None)
        log.error(
            "node_error",
            event="node_error",
            run_id=str(run_id),
            alert_id=self.alert_id,
            error_type=type(error).__name__,
            error_message=str(error),
        )

    # --- Tool callbacks ---

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id: UUID, **kwargs: Any) -> None:
        name = serialized.get("name", "unknown")
        self._tool_times[run_id] = time.monotonic()
        self._span_stack[run_id] = self._tracer.start_span(
            f"tool.{name}",
            attributes={"alert_id": self.alert_id},
        )
        # Never log input_str — may contain query parameters or credentials
        log.debug("tool_start", event="tool_start", tool_name=name, run_id=str(run_id), alert_id=self.alert_id)

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        t0 = self._tool_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - t0) * 1000) if t0 is not None else 0
        output_length = len(str(output))
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_attribute("duration_ms", duration_ms)
            span.set_attribute("output_length", output_length)
            span.set_status(StatusCode.OK)
            span.end()
        tool_name = kwargs.get("name", "unknown")
        # Never log raw output
        log.info(
            "tool_end",
            event="tool_end",
            tool_name=tool_name,
            run_id=str(run_id),
            alert_id=self.alert_id,
            duration_ms=duration_ms,
            output_length=output_length,
        )

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_status(StatusCode.ERROR, str(error))
            span.end()
        self._tool_times.pop(run_id, None)
        log.error(
            "tool_error",
            event="tool_error",
            run_id=str(run_id),
            alert_id=self.alert_id,
            error_type=type(error).__name__,
        )

    # --- LLM callbacks ---

    def on_llm_start(self, serialized: dict, prompts: list, *, run_id: UUID, **kwargs: Any) -> None:
        model = (serialized.get("id") or ["unknown"])[-1]
        self._llm_times[run_id] = time.monotonic()
        self._span_stack[run_id] = self._tracer.start_span(
            "llm.ollama",
            attributes={
                "alert_id": self.alert_id,
                "gen_ai.request.model": model,
            },
        )
        # Never log prompt text
        log.debug("llm_start", event="llm_start", model=model, run_id=str(run_id), alert_id=self.alert_id)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        t0 = self._llm_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - t0) * 1000) if t0 is not None else 0
        token_usage = {}
        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
        prompt_tokens = token_usage.get("prompt_tokens")
        completion_tokens = token_usage.get("completion_tokens")
        model = kwargs.get("name", "unknown")
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_attribute("duration_ms", duration_ms)
            if prompt_tokens is not None:
                span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
            if completion_tokens is not None:
                span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
            span.set_status(StatusCode.OK)
            span.end()
        log.info(
            "llm_end",
            event="llm_end",
            model=model,
            run_id=str(run_id),
            alert_id=self.alert_id,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        span = self._span_stack.pop(run_id, None)
        if span:
            span.set_status(StatusCode.ERROR, str(error))
            span.end()
        self._llm_times.pop(run_id, None)
        log.error(
            "llm_error",
            event="llm_error",
            run_id=str(run_id),
            alert_id=self.alert_id,
            error_type=type(error).__name__,
        )

    def end_root_span(self, error: Exception | None = None) -> None:
        if error is not None:
            self._root_span.set_status(StatusCode.ERROR, str(error))
        else:
            self._root_span.set_status(StatusCode.OK)
        self._root_span.end()
        context.detach(self._root_token)
