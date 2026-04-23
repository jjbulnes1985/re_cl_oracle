#!/usr/bin/env python3
"""
run_tests.py — RE_CL test runner with coverage and reporting.

Usage:
    python scripts/run_tests.py                    # all tests
    python scripts/run_tests.py --fast             # skip slow tests
    python scripts/run_tests.py --module scoring   # specific module
    python scripts/run_tests.py --coverage         # with coverage report
"""
import subprocess, sys, argparse
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser(description="RE_CL test runner")
    parser.add_argument("--fast", action="store_true", help="Skip slow tests")
    parser.add_argument("--module", help="Test module (scoring, api, features, etc.)")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--html", action="store_true", help="Generate HTML coverage report")
    parser.add_argument("-v", "--verbose", action="store_true", default=True)
    args = parser.parse_args()

    cmd = [sys.executable, "-m", "pytest"]

    if args.verbose:
        cmd.append("-v")

    if args.fast:
        cmd.extend(["-m", "not slow"])

    if args.module:
        cmd.append(f"tests/test_{args.module}.py")
    else:
        cmd.append("tests/")

    if args.coverage:
        cmd.extend(["--cov=src", "--cov-report=term-missing"])
        if args.html:
            cmd.append("--cov-report=html:data/exports/coverage_html")

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_DIR)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
