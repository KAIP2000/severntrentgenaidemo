from langchain.agents.middleware import ModelCallLimitMiddleware, ModelRetryMiddleware, ToolCallLimitMiddleware


def is_transient_model_error(exc: Exception) -> bool:
    """Retry provider throttling, timeouts and server-side availability failures."""
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429} or (isinstance(status_code, int) and status_code >= 500):
        return True
    if any(marker in type(exc).__name__.lower() for marker in ("timeout", "connection")):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("timed out", "timeout", "temporarily unavailable", "high demand", "resource exhausted"))


def water_operations_middleware():
    """Cross-cutting safeguards layered on top of the standard Deep Agents middleware stack.

    Deep Agents supplies TodoList, Filesystem, SubAgent and Summarization middleware. These
    additions bound each run; action approval is configured through ``interrupt_on`` at agent
    construction so LangChain can pause before the protected tool executes.
    """
    return [
        ModelRetryMiddleware(
            max_retries=5,
            retry_on=is_transient_model_error,
            on_failure="error",
            initial_delay=2.0,
            backoff_factor=2.0,
            max_delay=30.0,
            jitter=True,
        ),
        # Multi-domain investigations can include the root agent plus several
        # specialist task runs. Leave enough budget for final synthesis.
        ModelCallLimitMiddleware(run_limit=24, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=48, exit_behavior="error"),
    ]
