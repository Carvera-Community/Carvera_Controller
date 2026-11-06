# Contributor's Guide

Thank you for your interest in contributing to our project! We welcome contributions in the form of bug reports, feature requests, documentation improvements, and code.

## How to Contribute

### Reporting Issues

1. **Search Existing Issues:** Before reporting, search the [issues page](https://github.com/Carvera-Community/Carvera_Controller/issues) to see if it has already been reported.
2. **Create a New Issue:** If your issue is not listed, open a new issue [here](https://github.com/Carvera-Community/Carvera_Controller/issues/new). Please provide a clear and descriptive title and include steps to reproduce the problem, and which versions of the Controller and Machine firmware you are using.

### Requesting Features

1. **Check Current Projects:** Look at our [project board](https://trello.com/b/qKxPlEbk/carvera-community-firmware-controller-and-other-tech) to see if the feature is being discussed.
2. **Suggest a Feature:** Open an issue titled "Feature Request: [Your Feature]" and explain why it would be useful.

### Contributing Code

1. **Open an Issue First:** Before starting any development, please open an issue to discuss your proposed changes or features. This helps ensure your efforts are aligned with the project's priorities and increases the likelihood of PR acceptance.
2. **Get Maintainer Input:** Wait for feedback or approval from the maintainers on your proposed changes. They might provide guidance or suggest an approach that fits best with the current project direction.
3. **Fork the Repository:** Once your idea has the blessing of a maintainer, click on the "Fork" button at the top of the repository page.
4. **Clone your Fork:** Clone your fork to your local machine using `git clone`.
5. **Create a Branch:** Use `git checkout -b feature-name` to create a new branch for your changes.
6. **Make Changes:** Implement your changes. For a user-visible change, add a changelog fragment as described in [Changelog](#changelog).
7. **Test Your Changes:** Ensure your changes don’t break existing functionality or introduce new bugs. Run the quality checks and tests before opening the PR. See the [Quality Checks section in the README](README.md#quality-checks) for details on the tools and what they enforce.
8. **Commit Your Changes:** Write a concise and descriptive commit message.
9. **Push and Open a Pull Request:** Push your branch to your fork and open a pull request from your branch and use the `develop` branch as the destination. In the Pull Request please describe what issue you are resolving, and summarize the changes.

### PR Requirements

When you are working on a pull request, please adhere to the following requirements:

- Pull requests should be limited to one feature, or one bugfix/issue,
  or small set of highly related issues that have real world impact on the machines.
- Pull requests should be standalone and based on the `develop` branch unless there is
  a very good reason for them to depend on each other.
- Issues and PR bodies are for human to human communication. If using AI assistance,
  you are responsible for reviewing the content and not submitting something that
  you wouldn't write yourself.
- The expectation for all PRs is that the submitter has done everything reasonable
  to review and test the PR on their side. This includes running the code against
  your own machine hardware.
- We allow AI assisted pull requests in this repository. Please fill out the relevant information in the
  pull request template.
- Do not scan the code base with the express purpose of bulk creating issues/PRs
  without prior approval from maintainers.


## Changelog

User-visible changes get a news fragment into the `changelog.d` directory. The release process runs `towncrier build`, which folds those fragments into `CHANGELOG.md` and removes them. Add the fragment with your change, and leave the build step to the release.

Create a fragment from the repository root:

```bash
poetry run towncrier create
```

Towncrier asks for an issue number and a fragment type, then opens an editor.

- Enter the issue number when the change has one, for example `912`.
- Enter `+` when it does not. Towncrier appends a random id so the filename stays unique.

The fragment type is one of:

- `enhancement` for new behavior, rendered as `- Enhancement: …`
- `changed` for a change to existing behavior, rendered as `- Changed: …`
- `fixed` for a bug fix, rendered as `- Fixed: …`
- `removed` for a removal, rendered as `- Removed: …`

Write the description only. The build adds the bullet and the type prefix. A `fixed` fragment containing:

```text
Android builds were incorrectly detecting the default language
```

becomes:

```text
- Fixed: Android builds were incorrectly detecting the default language
```

To write the fragment without opening an editor, pass the filename and the text. Towncrier saves it in `changelog.d/` and adds a `.md` suffix:

```bash
poetry run towncrier create 912.fixed --content "Commands sent using the Send buttons are now added to the MDI history"
```

For a change with no issue, put a short slug after `+`:

```bash
poetry run towncrier create +mdi-history.fixed --content "Commands sent using the Send buttons are now added to the MDI history"
```

## Quality Checks

Run the configured hooks before opening a pull request:

```bash
poetry run pre-commit run --all-files
```

Run the test suite separately:

```bash
poetry run python -m pytest tests -q
```

For targeted checks, run the individual Poetry commands listed in the [Quality Checks section in the README](README.md#quality-checks).
