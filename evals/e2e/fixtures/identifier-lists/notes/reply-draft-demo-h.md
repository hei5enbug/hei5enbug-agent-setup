Holding the lock for the whole rebuild keeps a second refresh from reading rows that the first one has half written.

- Verified with `python3 -m pytest -q`: all tests passed.
- Added `test_demo_alpha`, `test_demo_beta`, and `test_demo_gamma`.
