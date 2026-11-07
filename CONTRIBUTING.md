# Contributing

1. Fork the repo and create a branch.
2. `pip install -r requirements.txt`
3. Make your change and add or update tests in `tests/`.
4. Run `python -m pytest -q` — all tests must pass.
5. Open a pull request describing what changed and why.

UI styling lives in `theme.py`; document logic lives in `core/`. Please do not add features that send documents to external services — TOKENFORGE is local-first by design.
