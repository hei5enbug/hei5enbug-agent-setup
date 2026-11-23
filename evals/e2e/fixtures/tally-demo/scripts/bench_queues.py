"""Print the work each queue library needs for the same 2,000 put and get calls; deterministic and quick."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from queues import alpha_queue, beta_queue  # noqa: E402

CALLS = 2000


def run(module) -> int:
    for number in range(CALLS):
        module.put("bench", str(number))
    for _ in range(CALLS):
        module.get("bench")
    return module.STEPS


if __name__ == "__main__":
    print(f"alpha: {run(alpha_queue)} steps for {CALLS * 2} calls")
    print(f"beta: {run(beta_queue)} steps for {CALLS * 2} calls")
