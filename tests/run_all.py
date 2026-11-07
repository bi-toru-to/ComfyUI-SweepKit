"""Run every SweepKit test suite and exit non-zero if any fails.

Usage (from anywhere):
    python tests/run_all.py            # all suites
    python tests/run_all.py -v         # also stream each suite's output

Python suites run with the same interpreter that runs this script (it needs
numpy and Pillow; ComfyUI's embedded python works). JS suites need `node`
on PATH; if node is missing they are reported as SKIPPED and the run fails,
so a missing toolchain can't masquerade as a pass.
"""

import os
import shutil
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(TESTS_DIR)

PY_SUITES = ["logic_test.py", "run_integration.py", "test_modular_pipeline.py"]
JS_SUITES = [
    "js_hidelora_test.mjs",
    "js_look_test.mjs",
    "js_pick_test.mjs",
    "js_polling_test.mjs",
    "js_soft_test.mjs",
    "js_socket_test.mjs",
    "js_summary_test.mjs",
]


def run(cmd, verbose):
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=PKG_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if verbose or proc.returncode != 0:
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
    return proc.returncode, time.time() - t0


def main():
    verbose = "-v" in sys.argv[1:]
    results = []
    for name in PY_SUITES:
        code, dt = run([sys.executable, "-B", "-X", "utf8", os.path.join(TESTS_DIR, name)], verbose)
        results.append((name, "PASS" if code == 0 else f"FAIL (exit {code})", dt))
    node = shutil.which("node")
    for name in JS_SUITES:
        if node is None:
            results.append((name, "SKIPPED (node not found)", 0.0))
            continue
        code, dt = run([node, os.path.join(TESTS_DIR, name)], verbose)
        results.append((name, "PASS" if code == 0 else f"FAIL (exit {code})", dt))

    print("\n" + "=" * 60)
    for name, status, dt in results:
        print(f"  {status:<28} {name}  ({dt:.1f}s)")
    failed = [r for r in results if r[1] != "PASS"]
    print("=" * 60)
    print(f"{len(results) - len(failed)}/{len(results)} suites passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
