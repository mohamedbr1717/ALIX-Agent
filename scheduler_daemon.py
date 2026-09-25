#!/usr/bin/env python3
"""ALIX scheduler daemon: runs due scheduled tasks unattended.

Usage (Termux):
    cd ~/ALIX-Agent
    nohup python3 scheduler_daemon.py > scheduler/daemon.log 2>&1 &

Or auto-start on boot with Termux:Boot
(~/.termux/boot/start-alix-scheduler.sh):
    #!/data/data/com.termux/files/usr/bin/sh
    cd ~/ALIX-Agent
    nohup python3 scheduler_daemon.py > scheduler/daemon.log 2>&1 &

Notes:
- One daemon only: a pid file refuses a second instance.
- Every tick (60s) due tasks run in a FRESH agent with
  scheduled_mode policy: destructive tools are never allowed
  unattended (fail-closed); other tools only up to the ceiling
  the task was granted at schedule time ("allow").
- Results append to scheduler/runs.log (JSON lines).
- Android Doze: after sleep, overdue tasks run once (catch-up)
  unless older than max_lateness_hours, then marked missed.
- Stop: kill the pid in scheduler/daemon.pid, or Ctrl+C.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent),
)

from core.agent import ALIXAgent  # noqa: E402
from core.feature_bridge import (  # noqa: E402
    build_run_due_tasks_use_case,
    build_task_store,
)

TICK_SECONDS = 60


def scheduler_dir() -> Path:
    return Path.home() / "ALIX-Agent" / "scheduler"


class AgentTaskExecutor:
    """Run the prompt in a fresh agent under scheduled policy.

    Duck-typed to the scheduler's TaskExecutorPort (no direct
    features/ import: entry points wire through core/ only).
    """

    def execute_task(
        self,
        prompt: str,
        allow: str,
    ) -> str:
        agent = ALIXAgent()
        agent.policy.scheduled_mode = True
        agent.policy.scheduled_allow = allow

        try:
            return agent.run(prompt)
        finally:
            try:
                agent.policy.scheduled_mode = False
            except Exception:
                pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def ensure_single_instance(
    pid_file: Path,
) -> None:
    if pid_file.exists():

        try:
            old_pid = int(
                pid_file.read_text().strip()
            )
        except ValueError:
            old_pid = 0

        if old_pid and _pid_alive(old_pid):
            print(
                f"daemon already running (pid {old_pid}), "
                "exiting."
            )
            sys.exit(1)

    pid_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    pid_file.write_text(str(os.getpid()))


def append_run_log(
    log_file: Path,
    outcome: dict,
) -> None:
    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = (
        datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )

    for entry in (
        outcome.get("ran", [])
        + outcome.get("missed", [])
        + outcome.get("failed", [])
    ):

        line = json.dumps(
            {
                "at": stamp,
                "task_id": entry.get("id"),
                "name": entry.get("name"),
                "status": entry.get("status"),
                "result": entry.get("result", "")[:2000],
            },
            ensure_ascii=False,
        )

        with log_file.open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(line + "\n")


def tick() -> None:
    store = build_task_store()

    use_case = build_run_due_tasks_use_case(
        store=store,
        executor=AgentTaskExecutor(),
    )

    outcome = use_case.execute()

    if (
        outcome["ran"]
        or outcome["missed"]
        or outcome["failed"]
    ):
        append_run_log(
            scheduler_dir() / "runs.log",
            outcome,
        )

        print(
            f"[{outcome['checked_at']}] "
            f"ran={len(outcome['ran'])} "
            f"missed={len(outcome['missed'])} "
            f"failed={len(outcome['failed'])}",
            flush=True,
        )


def main() -> None:
    ensure_single_instance(
        scheduler_dir() / "daemon.pid"
    )

    print(
        f"[scheduler] daemon started "
        f"(pid {os.getpid()}), tick={TICK_SECONDS}s",
        flush=True,
    )

    try:

        while True:
            tick()
            time.sleep(TICK_SECONDS)

    except KeyboardInterrupt:
        print(
            "\n[scheduler] stopped by user.",
            flush=True,
        )


if __name__ == "__main__":
    main()
