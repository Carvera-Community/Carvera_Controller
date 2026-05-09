"""Unit-test setup for tests that import Kivy.

Isolates Kivy state to a temp directory so unit tests don't read or mutate
the user's real ~/.kivy config. Must run before any Kivy import — pytest
loads conftest.py before collecting test modules in the same directory.
"""

import os
import shutil
import tempfile

_kivy_home = tempfile.mkdtemp(prefix="kivy_unit_test_")
os.environ.setdefault("KIVY_HOME", _kivy_home)
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_kivy_home, ignore_errors=True)
