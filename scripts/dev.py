"""Run the two local development processes and stop their process groups together."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


def signal_process_group(process, force=False):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except ProcessLookupError:
        pass


def supervise(commands, directory):
    stopping = threading.Event()
    processes = []
    previous_handlers = {}

    def request_stop(_number, _frame):
        stopping.set()

    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[number] = signal.signal(number, request_stop)
        for command in commands:
            processes.append(subprocess.Popen(
                command, cwd=directory, start_new_session=(os.name == "posix"),
            ))
        while not stopping.wait(0.1):
            for process in processes:
                status = process.poll()
                if status is not None:
                    return status if status >= 0 else 128 - status
        return 0
    finally:
        for process in processes:
            signal_process_group(process)
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                signal_process_group(process, force=True)
                process.wait()
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    directory = Path(__file__).resolve().parents[1]
    print("Launching local API and UI. Read each process's output for its ready address.", flush=True)
    raise SystemExit(supervise([
        [sys.executable, "-m", "backend.main"],
        ["npm", "--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1"],
    ], directory))
