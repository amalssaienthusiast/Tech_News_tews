"""Unit tests for the SupervisedAPIProcess class in main.py."""
import sys
import time
import signal
import threading
from pathlib import Path

# Make sure the repo root is on the path so we can import main
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


def test_supervised_api_process_imports():
    """The SupervisedAPIProcess class can be imported."""
    from main import SupervisedAPIProcess
    assert SupervisedAPIProcess is not None


def test_supervised_api_process_init():
    """Constructor sets attributes correctly."""
    from main import SupervisedAPIProcess
    api = SupervisedAPIProcess(host="127.0.0.1", port=9999, max_restart_attempts=2, restart_cooldown=0.1)
    assert api.host == "127.0.0.1"
    assert api.port == 9999
    assert api.max_restart_attempts == 2
    assert api.restart_cooldown == 0.1
    assert api._process is None
    assert api.is_alive() is False  # not started yet


def test_supervised_api_process_check_and_restart_when_not_started():
    """check_and_restart() returns False when not started (should_run=False)."""
    from main import SupervisedAPIProcess
    api = SupervisedAPIProcess()
    # Not started yet — check_and_restart should return False
    assert api.check_and_restart() is False


def test_supervised_api_process_stop_when_not_started():
    """stop() is a no-op when the process was never started."""
    from main import SupervisedAPIProcess
    api = SupervisedAPIProcess()
    # Should not raise
    api.stop(timeout=1.0)
    assert api._process is None


def test_argparse_defaults():
    """The argparse defaults are correct."""
    import main
    # Simulate no args
    sys.argv = ["main.py"]
    args = main.parse_args()
    assert args.with_api is False
    assert args.no_api is False
    assert args.host == "0.0.0.0"
    assert args.port == 8000
    assert args.log_level == "INFO"


def test_argparse_with_api():
    """--with-api flag is parsed correctly."""
    import main
    sys.argv = ["main.py", "--with-api", "--port", "9999"]
    args = main.parse_args()
    assert args.with_api is True
    assert args.port == 9999


def test_argparse_no_api():
    """--no-api flag is parsed correctly."""
    import main
    sys.argv = ["main.py", "--no-api"]
    args = main.parse_args()
    assert args.no_api is True
    assert args.with_api is False


def test_argparse_mutually_exclusive():
    """--with-api and --no-api are mutually exclusive."""
    import main
    sys.argv = ["main.py", "--with-api", "--no-api"]
    with pytest.raises(SystemExit):
        main.parse_args()


if __name__ == "__main__":
    test_supervised_api_process_imports()
    test_supervised_api_process_init()
    test_supervised_api_process_check_and_restart_when_not_started()
    test_supervised_api_process_stop_when_not_started()
    test_argparse_defaults()
    test_argparse_with_api()
    test_argparse_no_api()
    test_argparse_mutually_exclusive()
    print("All SupervisedAPIProcess tests passed.")
