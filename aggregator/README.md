# Aggregator (Binance Trades → `aggregated.csv`)

This service connects to the Binance WebSocket **trade** stream and produces a compact, time-based market feed from executed trades.

## What it does

- Subscribes to the Binance `@trade` stream.
- Logs raw trades to `trades_log.txt`.
- Every `AGG_INTERVAL` seconds (default: 60):
  - aggregates trades into a single row of metrics,
  - appends the row to `aggregated.csv`,
  - trims `aggregated.csv` to a bounded size,
  - clears `trades_log.txt` for the next interval.

## Output

Default paths:

- Trade log: `/app/logs/trades_log.txt`
- Aggregated feed: `/app/feed/aggregated.csv`

CSV header:

`Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice`

### Column meanings

- **Timestamp** — aggregation timestamp (`YYYY-MM-DD HH:MM:SS`)
- **Trades** — number of trades in the interval
- **TotalQty** — total traded quantity
- **AvgSize** — `TotalQty / Trades`
- **BuyQty** — quantity attributed to buy aggressor trades
- **SellQty** — quantity attributed to sell aggressor trades
- **AvgPrice** — quantity-weighted average price (VWAP-like)
- **ClosePrice** — last trade price observed in the interval

## Configuration

Current implementation uses constants defined in the script:

- `AGG_INTERVAL` (default: `60`)
- `MAX_RECORDS` (default: `1500`)

## Quick demo (Aggregator live feed)

Requirements: Docker Desktop

```powershell
docker compose -f .\docker-compose.demo.yml up -d
.\demo_aggregator.ps1
Stop:

powershell
docker compose -f .\docker-compose.demo.yml down
Manual check:

powershell
Get-Content .\data\feed\aggregated.csv -Tail 5
Get-Content .\data\logs\trades_log.txt -Tail 10

## Install / Run
```bash
pip install websocket-client
python aggregator.py






