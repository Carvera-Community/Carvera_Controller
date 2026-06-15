"""Run screenshot-based visual regression tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VISUAL_TEST_GLOB = "test_visual_regression*.py"
XVFB_SERVER_ARGS = "-screen 0 1920x1080x24 -dpi 96 -nolisten tcp"
VISUAL_SUBPROCESS_ENV = {
    "KIVY_DPI": "96",
    "KIVY_METRICS_DENSITY": "1",
    "KIVY_METRICS_FONTSCALE": "1",
    "LIBGL_ALWAYS_SOFTWARE": "1",
}


def visual_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(VISUAL_SUBPROCESS_ENV)
    return env


def visual_test_paths() -> list[str]:
    return [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "tests" / "integration").glob(VISUAL_TEST_GLOB))
    ]


def visual_pytest_command(mode: str, update: bool, target: str, extra_pytest_args: Sequence[str]) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        target,
        "--visual-run",
        f"--visual-reference-mode={mode}",
    ]
    if update:
        command.append("--update-references")
    command.extend(extra_pytest_args)
    return command


def split_pytest_selection_and_options(extra_pytest_args: Sequence[str]) -> tuple[list[str], list[str]]:
    selection_args: list[str] = []
    option_args: list[str] = []
    value_expected = False
    options_with_values = {
        "-k",
        "-m",
        "-W",
        "--color",
        "--log-level",
        "--maxfail",
        "--tb",
        "--timeout",
    }
    for arg in extra_pytest_args:
        if value_expected:
            option_args.append(arg)
            value_expected = False
            continue
        if not arg.startswith("-"):
            selection_args.append(arg)
            continue
        option_args.append(arg)
        option_name = arg.split("=", 1)[0]
        if option_name in options_with_values and "=" not in arg:
            value_expected = True
    return selection_args, option_args


def collect_visual_tests_command(mode: str, extra_pytest_args: Sequence[str]) -> list[str]:
    selection_args, option_args = split_pytest_selection_and_options(extra_pytest_args)
    targets = selection_args if selection_args else visual_test_paths()
    return [
        sys.executable,
        "-m",
        "pytest",
        *targets,
        "--visual-run",
        f"--visual-reference-mode={mode}",
        "--collect-only",
        "-q",
        *option_args,
    ]


def pytest_option_args(extra_pytest_args: Sequence[str]) -> list[str]:
    _selection_args, option_args = split_pytest_selection_and_options(extra_pytest_args)
    return option_args


def collect_visual_nodeids(mode: str, extra_pytest_args: Sequence[str]) -> tuple[int, list[str]]:
    result = subprocess.run(
        collect_visual_tests_command(mode=mode, extra_pytest_args=extra_pytest_args),
        cwd=REPO_ROOT,
        env=visual_subprocess_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(result.stdout, end="")
        return result.returncode, []
    nodeids = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    return 0, nodeids


def split_pytest_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return list(argv), []
    separator = argv.index("--")
    return list(argv[:separator]), list(argv[separator + 1 :])


def run_command(command: Sequence[str]) -> int:
    return subprocess.run(command, cwd=REPO_ROOT, env=visual_subprocess_env(), check=False).returncode


def isolated_visual_test_command(
    mode: str,
    update: bool,
    nodeid: str,
    pytest_args: Sequence[str],
    xvfb: bool,
) -> list[str]:
    command = visual_pytest_command(
        mode=mode,
        update=update,
        target=nodeid,
        extra_pytest_args=pytest_option_args(pytest_args),
    )
    if not xvfb:
        return command
    return ["xvfb-run", "-a", "-s", XVFB_SERVER_ARGS, *command]


def run_isolated_visual_nodeid(
    mode: str,
    update: bool,
    nodeid: str,
    pytest_args: Sequence[str],
    xvfb: bool,
) -> tuple[int, str]:
    result = subprocess.run(
        isolated_visual_test_command(mode=mode, update=update, nodeid=nodeid, pytest_args=pytest_args, xvfb=xvfb),
        cwd=REPO_ROOT,
        env=visual_subprocess_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def run_visual_tests(mode: str, update: bool, pytest_args: Sequence[str], jobs: int, xvfb: bool) -> int:
    collect_result, nodeids = collect_visual_nodeids(mode=mode, extra_pytest_args=pytest_args)
    if collect_result != 0:
        return collect_result
    if not nodeids:
        print("No visual regression tests selected.")
        return 5

    jobs = max(1, jobs)
    if jobs > 1 and not xvfb:
        raise SystemExit("Parallel visual jobs require --xvfb so each worker gets an isolated display.")

    if jobs == 1:
        for nodeid in nodeids:
            print(f"\n===== {nodeid} =====", flush=True)
            result = run_command(
                isolated_visual_test_command(
                    mode=mode,
                    update=update,
                    nodeid=nodeid,
                    pytest_args=pytest_args,
                    xvfb=xvfb,
                )
            )
            if result != 0:
                return result
        return 0

    failed = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(run_isolated_visual_nodeid, mode, update, nodeid, pytest_args, xvfb): nodeid
            for nodeid in nodeids
        }
        for future in as_completed(futures):
            nodeid = futures[future]
            result, output = future.result()
            print(f"\n===== {nodeid} =====", flush=True)
            print(output, end="")
            if result != 0 and failed == 0:
                failed = result
    return failed


def add_visual_options(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of isolated visual pytest subprocesses to run at once.",
    )
    subparser.add_argument(
        "--xvfb",
        action="store_true",
        help="Run each isolated visual pytest subprocess under xvfb-run.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("local-update", "Generate ignored host-local references."),
        ("local-compare", "Compare against ignored host-local references."),
        ("reference-update", "Generate committed references in the current environment."),
        ("reference-compare", "Compare against committed references in the current environment."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        add_visual_options(command)

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser_args, pytest_args = split_pytest_args(raw_argv)
    args, unknown_args = build_parser().parse_known_args(parser_args)
    args.pytest_args = pytest_args + unknown_args
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command_config = {
        "local-update": ("local", True),
        "local-compare": ("local", False),
        "reference-update": ("committed", True),
        "reference-compare": ("committed", False),
    }
    mode, update = command_config[args.command]
    return run_visual_tests(
        mode=mode,
        update=update,
        pytest_args=args.pytest_args,
        jobs=args.jobs,
        xvfb=args.xvfb,
    )


if __name__ == "__main__":
    raise SystemExit(main())
