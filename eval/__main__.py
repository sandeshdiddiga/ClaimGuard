"""python -m eval [--all-ultra] [--only NAME ...]: run the samples live and write eval/results.md."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.llm import LLMClient
from eval.report import render_report
from eval.run import Run
from eval.runner import CASES, all_ultra_overrides, models_env, run_cases, temp_work_dir

ROOT = Path(__file__).resolve().parent.parent
RUNS = Path(__file__).resolve().parent / "runs"
RESULTS = Path(__file__).resolve().parent / "results.md"


def load_run(mode: str) -> Run | None:
    path = RUNS / f"{mode}.json"
    return Run.model_validate_json(path.read_text()) if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    parser.add_argument("--all-ultra", action="store_true", help="run every model step on Nemotron 3 Ultra")
    parser.add_argument("--only", nargs="+", choices=[c.name for c in CASES], help="a subset; prints, writes nothing")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if not os.environ.get("NEBIUS_API_KEY"):
        print("NEBIUS_API_KEY is not set (see .env.example): the eval runs the live models.", file=sys.stderr)
        return 2
    cases = [c for c in CASES if not args.only or c.name in args.only]
    mode = "all_ultra" if args.all_ultra else "routed"
    overrides, notes = all_ultra_overrides(LLMClient()) if args.all_ultra else ({}, [])

    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    with temp_work_dir() as work, models_env(overrides):
        run = run_cases(
            cases, mode=mode, reference_db=ROOT / "data" / "claimguard.db", samples_dir=ROOT / "samples",
            work_dir=Path(work), notes=notes, progress=progress,
        )
    routed, ultra = (run, None) if mode == "routed" else (None, run)
    if args.only:
        print(render_report(routed, ultra))
        return 0
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"{mode}.json").write_text(run.model_dump_json(indent=1) + "\n")
    RESULTS.write_text(render_report(load_run("routed"), load_run("all_ultra")))
    print(f"wrote {RESULTS.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
