from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.evaluation.langsmith_runner import run_experiment, seed_dataset
from app.evaluation.scenarios import SCENARIOS


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def print_report(report, url: str | None = None) -> None:
    print("\nWater Operations Harness Evaluation")
    print("=" * 38)
    print(f"Harness Success       {_percent(report.summary.get('harness_success_rate')):>8}")
    print(f"Investigation Success {_percent(report.summary.get('investigation_success_rate')):>8}")
    print("\nScenarios")
    for item in report.scenarios:
        print(f"{item.result:7} {item.scenario_id:18} tools={item.record.tool_calls:<2} models={item.record.model_calls:<2} {item.record.duration_ms:>6}ms")
    if url:
        print(f"\nLangSmith: {url}")


async def _live(settings: Settings) -> None:
    report, url = await run_experiment(settings)
    print_report(report, url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Water-operations agentic harness evaluation")
    parser.add_argument("command", choices=["seed", "live"])
    args = parser.parse_args()
    settings = Settings()
    if args.command == "seed":
        dataset = seed_dataset(settings)
        print(f"Seeded {len(SCENARIOS)} scenarios into {dataset.name}")
    else:
        if not settings.live_model_available:
            raise SystemExit("Live evaluation requires AGENT_EXECUTION_MODE=live and a valid model API key.")
        asyncio.run(_live(settings))


if __name__ == "__main__":
    main()
