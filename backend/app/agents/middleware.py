from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware


def water_operations_middleware():
    """Cross-cutting safeguards layered on top of the standard Deep Agents middleware stack.

    Deep Agents supplies TodoList, Filesystem, SubAgent and Summarization middleware. These
    additions bound each run; action approval is configured through ``interrupt_on`` at agent
    construction so LangChain can pause before the protected tool executes.
    """
    return [
        ModelCallLimitMiddleware(run_limit=12, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=24, exit_behavior="error"),
    ]

