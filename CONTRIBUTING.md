# Contributing to SpindleSage

Thanks for your interest. SpindleSage is at the research and architecture stage, so issues that discuss design, datasets or experiments are as welcome as code.

## Development setup

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pytest
```

## Ground rules

- **Safety first.** Machine connectivity is read-only by default. Never add code that sends control commands to a PLC or CNC without an explicit, reviewed human-approval path.
- **No data in git.** Datasets are downloaded by scripts in `datasets/download_scripts/`. Record source, version, licence and preprocessing in `datasets/metadata/`.
- **No unsupported claims.** Results in docs or reports must be backed by a reproducible experiment in `experiments/`. Synthetic data is always labelled as synthetic.
- **Check licences.** Confirm a new dependency's licence is compatible with Apache 2.0 before adding it.
- **Tests and lint pass.** CI runs Ruff and Pytest on every pull request.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each pull request focused on one change.
3. Describe what changed and how you tested it.
