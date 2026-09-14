"""A shared, sleeping admission gate for background AI work on this machine.

Interactive chat never takes this lock. Job identity, prompts, permissions and
processing state remain with the caller. Waiting jobs are not marked complete.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import os


@contextmanager
def background_slot(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required")
    path = Path(args.lock)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    # exec keeps the locked descriptor alive for the actual runner's lifetime,
    # including its watchdog. There is no supervising Python left in RAM.
    os.set_inheritable(lock_fd, True)
    os.environ["ELEVATE_BACKGROUND_LOCK_FD"] = str(lock_fd)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
