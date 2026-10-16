# RrepoTrace - Python debugging tool

## Project purpose

ReproTrace is intended to help capture, inspect, and compare execution traces for reproducibility workflows. The project focuses on analyzing command execution, environment metadata, and trace artifacts so that debugging and reproduction are easier.

## Repository layout

The most important files and directories are:

- `README.md` — project overview, setup, and usage guidance.
- `pyproject.toml` — Python package metadata and dependency configuration.
- `requirements*.txt` — environment dependencies if present.
- `src/` — main application source code.
- `tests/` — automated tests for validation.

## Key files to inspect first

Before making changes, read these files in order:

1. `README.md`
2. `pyproject.toml`
3. `src/` package entry points and core modules
4. `tests/` relevant test files

## Development conventions

- Prefer small, targeted edits that match the existing code style.
- Keep behavior consistent with the current architecture and module boundaries.
- Update or add tests when changing runtime behavior.
- Preserve compatibility with the supported Python version declared in `pyproject.toml`.
- Avoid broad refactors unless the task explicitly requires them.

## Code Quality Standards
- Write clear, readable Python code that follows the project’s existing style and naming conventions.
- Keep functions and classes focused on a single responsibility and favor small, composable abstractions.
- Prefer explicit, maintainable logic over clever or overly compact implementations.
- Add or update tests for behavioral changes, bug fixes, and new features.
- Validate changes with the narrowest relevant test command and ensure they pass in the supported Python environment.
- Preserve backward compatibility unless the task explicitly requires a breaking change.
- Avoid dead code, unnecessary dependencies, and broad refactors that are unrelated to the task.

## Typical workflow

- Understand the feature or bug from the issue and confirm expected behavior.
- Inspect the relevant modules under `src/` and the matching tests.
- Implement the smallest fix or feature change.
- Validate with the narrowest relevant test command.

## Documentation

- Use docstrings for public modules, classes, functions, and methods to explain purpose, arguments, return values, and edge cases.
- Keep docstrings concise and consistent with the project’s existing Python style.
- Prefer clear inline comments only when they clarify non-obvious logic or intent.
- Update README or other user-facing docs when behavior, configuration, or command usage changes.
- When fixing bugs or adding features, ensure the related tests and docs stay aligned with the implementation.

## Notes

- This file is meant to guide AI contributors and maintainers working in the repository.
- Follow the project’s conventions in the source tree rather than inventing a parallel structure.
- If there is ambiguity, prefer the patterns already established in the existing code and docs.
