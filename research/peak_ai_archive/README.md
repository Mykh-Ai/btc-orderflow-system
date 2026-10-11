# Peak AI archived research data

Large tables, query caches and the deliverable ZIP are preserved losslessly in split ZIP parts to fit the publishing connector limit. Code and smaller reports remain at their original paths.

From the repository root, run:

```sh
python research/peak_ai_archive/restore.py
```

The script verifies archive and file SHA-256 checksums and restores all original paths. It refuses to overwrite modified files. No third-party dependencies. These are existing research results; no backtest rerun is required.
