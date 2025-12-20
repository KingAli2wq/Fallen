import os
import subprocess
import sys


def run_repl_with_input(inp: str) -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cli = os.path.join(root, "cli.py")

    proc = subprocess.run(
        [sys.executable, cli, "repl"],
        input=inp,
        text=True,
        capture_output=True,
        cwd=root,
        timeout=10,
    )

    # REPL should exit cleanly after :q
    if proc.returncode != 0:
        raise AssertionError(f"REPL exited with code {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    return proc.stdout


def test_auto_print_expression():
    out = run_repl_with_input("1 + 2\n:q\n")
    if "3" not in out:
        raise AssertionError(f"Expected 3 in output.\nOUT:\n{out}")


def test_persistent_state_expression():
    out = run_repl_with_input("x =i 2\nx + 5\n:q\n")
    if "7" not in out:
        raise AssertionError(f"Expected 7 in output.\nOUT:\n{out}")


if __name__ == "__main__":
    test_auto_print_expression()
    test_persistent_state_expression()
    print("ok")
