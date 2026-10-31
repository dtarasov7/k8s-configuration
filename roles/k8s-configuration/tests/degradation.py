#!/usr/bin/env python3
"""Stop one disposable control-plane node, verify RBAC, always restart it."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kubeconfig")
    args = parser.parse_args()
    node = "kam-role-validation-control-plane2"
    # Container name is intentionally fixed to the dedicated integration fixture.
    subprocess.run(["docker", "stop", "--timeout", "10", node], check=True)
    try:
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("live_smoke.py")),
                "verify",
                args.kubeconfig,
            ],
            check=True,
        )
    finally:
        subprocess.run(["docker", "start", node], check=True)
    print("PASS: API and access reconciliation survive one control-plane failure")


if __name__ == "__main__":
    main()
