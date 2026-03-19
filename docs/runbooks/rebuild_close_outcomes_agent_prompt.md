# Rebuild Close Outcomes Agent Prompt

Use this prompt when you want an agent to connect to the VPS and rebuild the offline research datasets after a trade close.

## Prompt

```text
Connect to the project server and rebuild the offline research datasets for the UTC date of the closed trade.

Server access:
- ssh -F NUL root@95.216.139.172

Project root:
- /root/volume-alert

Important:
- Work from `/root/volume-alert`
- Use the project virtual environment: `.venv`
- Do not edit code
- Do not install packages unless explicitly required
- If a required input file is missing, stop and report it clearly

Steps:

1. Connect to the server.

2. Go to the project root:
- `cd /root/volume-alert`

3. Activate the virtual environment:
- `source .venv/bin/activate`

4. Verify the environment briefly:
- `python --version`
- `python -c "import pandas; print(pandas.__version__)"`

5. Verify required inputs for the target date `YYYY-MM-DD`:
- `/data/state/trade_outcomes.jsonl`
- `/data/archive/deltascout/YYYY-MM-DD.jsonl`

Use:
- `test -f /data/state/trade_outcomes.jsonl && echo TRADE_OUTCOMES_OK || echo TRADE_OUTCOMES_MISSING`
- `test -f /data/archive/deltascout/YYYY-MM-DD.jsonl && echo DELTASCOUT_ARCHIVE_OK || echo DELTASCOUT_ARCHIVE_MISSING`

6. Rebuild the offline datasets for `YYYY-MM-DD`:

- `python scripts/offline/build_phase1_derived.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets`
- `python scripts/offline/build_close_outcomes.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets`

7. Verify output files:
- `ls -lh /data/archive/datasets | tail -n 20`

8. Check the close outcomes artifact for the requested date.

If CSV exists:
- `head -n 20 /data/archive/datasets/close_outcomes_YYYY-MM-DD.csv`

If parquet exists instead of CSV:
- report that parquet was created and show the exact filename

Final response format:
- processed date
- python version used
- pandas version used
- whether both required input files existed
- commands executed
- files created or updated in `/data/archive/datasets`
- whether `close_outcomes_YYYY-MM-DD` was produced
- whether the closed trade appears in the output
- if anything failed, give the exact error and the step where it failed
```

## Notes

- `trade_outcomes.jsonl` is the canonical raw source for close outcomes.
- `build_close_outcomes.py` uses `trade_outcomes.jsonl` as the primary source and falls back to executor artifacts only when needed.
- `build_phase1_derived.py` and `build_close_outcomes.py` should be run from the project root with the virtual environment activated.
