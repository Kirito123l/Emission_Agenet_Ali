# Release Readiness

This file is a minimal shareability checklist for the current repository state. It is not a formal release process or packaging guide.

## What The Repository Is Ready For

The repository is currently in good shape for:

- sharing with collaborators for code review and active development
- local demos through the integrated API + web UI path
- local validation through `python main.py health` and `pytest`
- benchmark-style smoke runs through `python evaluation/run_smoke_suite.py`
- conservative, test-backed cleanup work

## What Is Stable Enough To Point People At

Use these as the current public-facing surfaces:

- [README.md](README.md)
- [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md)
- [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
- [RUNNING.md](RUNNING.md)
- [evaluation/README.md](evaluation/README.md)
- [examples/README.md](examples/README.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

Core supported workflows:

- `python run_api.py`
- `python main.py health`
- `pytest`
- `python evaluation/run_smoke_suite.py`

## What Is Still Evolving

- deeper `core/router.py` decomposition
- deeper `api/routes.py` decomposition
- evaluation methodology as a finalized paper package
- broader packaging/distribution polish
- pruning or reorganizing the full historical report trail

## Before Sharing The Repo

Run or verify:

```bash
python main.py health
pytest
python evaluation/run_smoke_suite.py
```

Also verify:

- root-level docs point to the same canonical workflows
- `.env.example` still reflects the current minimum setup story
- examples match the real supported commands
- no local secrets are being shared from `.env` or generated output

## What This Does Not Yet Claim

This repository is not yet claiming:

- a fully frozen public API
- a finished external release package
- a finalized contributor process for a large open-source community
- a publication-ready benchmark bundle with long-term artifact guarantees

## Good Sharing Posture Right Now

The best current framing is:

- active research/engineering prototype
- usable local app surface
- usable smoke-level evaluation harness
- improving docs, examples, and contributor guidance
- some internals intentionally still in conservative stabilization mode
