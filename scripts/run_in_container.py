"""Run a repository command inside the CI-like dependency container."""

from __future__ import annotations

import argparse
import os
import platform as platform_module
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "carvera-controller-ci:latest"
CONTAINERFILE_PATH = REPO_ROOT / "tests" / "integration" / "visual" / "Containerfile"


def default_container_platform() -> str | None:
    machine = platform_module.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "linux/arm64"
    if machine in {"x86_64", "amd64"}:
        return "linux/amd64"
    return None


def detect_engine(explicit_engine: str | None) -> str:
    if explicit_engine:
        return explicit_engine
    env_engine = os.environ.get("CARVERA_CI_ENGINE")
    if env_engine:
        return env_engine
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    raise SystemExit("No container engine found. Install Docker or Podman, or set CARVERA_CI_ENGINE.")


def container_build_command(engine: str, image: str, platform: str | None) -> list[str]:
    command = [engine, "build"]
    if platform:
        command.extend(["--platform", platform])
    command.extend(["-f", str(CONTAINERFILE_PATH), "-t", image, str(REPO_ROOT)])
    return command


def container_run_command(
    engine: str,
    image: str,
    repo_root: Path,
    platform: str | None,
    command_args: Sequence[str],
    use_host_user: bool,
) -> list[str]:
    command = [
        engine,
        "run",
        "--rm",
        "-e",
        "HOME=/tmp",
        "-e",
        "POETRY_VIRTUALENVS_IN_PROJECT=false",
    ]
    if platform:
        command.extend(["--platform", platform])
    command.extend(["-v", f"{repo_root}:/workspace", "-w", "/workspace"])
    if use_host_user and hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    command.append(image)
    command.extend(command_args)
    return command


def run_command(command: Sequence[str]) -> int:
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("docker", "podman"), default=None)
    parser.add_argument("--image", default=None)
    parser.add_argument("--platform", default=None, help="Container platform, for example linux/arm64.")
    parser.add_argument("--no-build", action="store_true", help="Reuse an already-built CI-like container image.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run in the container, after --.")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        raise SystemExit("Pass the command to run after --.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    engine = detect_engine(args.engine)
    image = args.image or os.environ.get("CARVERA_CI_IMAGE", DEFAULT_IMAGE)
    platform = args.platform or os.environ.get("CARVERA_CI_PLATFORM") or default_container_platform()
    if not args.no_build:
        build_result = run_command(container_build_command(engine=engine, image=image, platform=platform))
        if build_result != 0:
            return build_result
    return run_command(
        container_run_command(
            engine=engine,
            image=image,
            repo_root=REPO_ROOT,
            platform=platform,
            command_args=args.command,
            use_host_user=os.name != "nt",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
