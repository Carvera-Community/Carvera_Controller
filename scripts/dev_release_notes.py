import subprocess
import sys


def render_unreleased_notes():
    result = subprocess.run(
        [sys.executable, "-m", "towncrier", "build", "--draft", "--version", "unreleased"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)

    rendered = result.stdout.strip()
    if not any(line.startswith("- ") for line in rendered.splitlines()):
        return "No unreleased notes currently."
    return rendered


def main():
    unreleased_notes = render_unreleased_notes()

    dev_release_text = f"""# Welcome to the Dev Build Release Page for Carvera Controller Community!

## What is a Dev Build?

Dev builds are the latest versions of Carvera Controller Community, automatically compiled after every new commit to the `develop` branch. This means that each build incorporates the most recent changes and improvements. While these builds offer a glimpse into the ongoing development of Carvera Controller, keep in mind that they are still works in progress and may contain bugs or unstable features.

## Download Instructions:
1. Select the version that corresponds to your operating system.
2. Download and install/run the build.
3. Dive into the newest features and improvements!

## Please Note:

* Dev builds are developmental and may contain bugs.
* Your feedback is crucial. Please report any issues or suggestions on our GitHub page.

## Release notes
The follow changes are present in the dev build:

{unreleased_notes}
"""
    with open("dev-CHANGELOG.md", "w") as file:
        file.write(dev_release_text)


if __name__ == "__main__":
    main()
