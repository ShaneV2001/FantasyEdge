"""Cross-platform task runner (the Makefile delegates here so Windows works without `make`).

Usage: python tasks.py <setup|data|dev|api|web|test|lint|fmt|gen-api|train>
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def pnpm() -> list[str]:
    if shutil.which("pnpm"):
        return ["pnpm"]
    return ["corepack", "pnpm"]


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}  (in {cwd.relative_to(ROOT) or '.'})", flush=True)
    resolved = shutil.which(cmd[0]) or cmd[0]
    subprocess.run([resolved, *cmd[1:]], cwd=cwd, check=True)


def setup() -> None:
    run(["uv", "sync"], BACKEND)
    if FRONTEND.exists():
        run([*pnpm(), "install"], FRONTEND)


def data() -> None:
    run(["uv", "run", "python", "-m", "ingest.run", "all"], BACKEND)


def api() -> None:
    run(["uv", "run", "uvicorn", "app.main:app", "--reload", "--port", "8000"], BACKEND)


def web() -> None:
    run([*pnpm(), "dev"], FRONTEND)


def dev() -> None:
    procs = [
        subprocess.Popen(
            [shutil.which("uv") or "uv", "run", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
            cwd=BACKEND,
        )
    ]
    if FRONTEND.exists():
        procs.append(subprocess.Popen([shutil.which(pnpm()[0]) or pnpm()[0], *pnpm()[1:], "dev"], cwd=FRONTEND))
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


def lint() -> None:
    run(["uv", "run", "ruff", "check", "."], BACKEND)
    run(["uv", "run", "ruff", "format", "--check", "."], BACKEND)
    if FRONTEND.exists():
        run([*pnpm(), "run", "lint"], FRONTEND)


def fmt() -> None:
    run(["uv", "run", "ruff", "check", "--fix", "."], BACKEND)
    run(["uv", "run", "ruff", "format", "."], BACKEND)


def test() -> None:
    lint()
    run(["uv", "run", "pytest"], BACKEND)
    if FRONTEND.exists():
        run([*pnpm(), "run", "test"], FRONTEND)


def gen_api() -> None:
    run(["uv", "run", "python", "-m", "app.export_openapi", "../frontend/openapi.json"], BACKEND)
    run([*pnpm(), "run", "gen-api"], FRONTEND)


def train() -> None:
    print("Model training arrives in Phase 2 (Model v1).")


TASKS = {
    "setup": setup,
    "data": data,
    "dev": dev,
    "api": api,
    "web": web,
    "test": test,
    "lint": lint,
    "fmt": fmt,
    "gen-api": gen_api,
    "train": train,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    try:
        TASKS[sys.argv[1]]()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
