# Rebuild Close Outcomes Agent Prompt Short

```text
SSH to the server and rebuild the offline research datasets for UTC date `YYYY-MM-DD`.

Server:
- ssh -F NUL root@95.216.139.172

Commands to run:

cd /root/volume-alert
source .venv/bin/activate
python --version
python -c "import pandas; print(pandas.__version__)"
test -f /data/state/trade_outcomes.jsonl && echo TRADE_OUTCOMES_OK || echo TRADE_OUTCOMES_MISSING
test -f /data/archive/deltascout/YYYY-MM-DD.jsonl && echo DELTASCOUT_ARCHIVE_OK || echo DELTASCOUT_ARCHIVE_MISSING
python scripts/offline/build_phase1_derived.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
python scripts/offline/build_close_outcomes.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
ls -lh /data/archive/datasets | tail -n 20

If present, show:
- head -n 20 /data/archive/datasets/close_outcomes_YYYY-MM-DD.csv

In the final response report:
- processed date
- python version
- pandas version
- whether required input files existed
- commands executed
- files created or updated
- whether close_outcomes_YYYY-MM-DD was produced
- whether the closed trade is visible in the output
- exact error text if anything failed
```
