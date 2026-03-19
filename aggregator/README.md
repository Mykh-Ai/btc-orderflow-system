# Aggregator (Binance Trades -> `aggregated.csv`)

This service connects to the Binance WebSocket trade stream and produces a compact, time-based market feed from executed trades.

## What it does

- Subscribes to the Binance `@trade` stream.
- Logs raw trades to `trades_log.txt`.
- Every `AGG_INTERVAL` seconds (default: 60):
  - aggregates trades into a single row of metrics,
  - appends the row to `aggregated.csv`,
  - appends the same row to the daily feed archive,
  - trims `aggregated.csv` to a bounded size,
  - clears `trades_log.txt` for the next interval.

## Output

Default paths:

- Trade log: `/data/logs/trades_log.txt`
- Aggregated feed: `/data/feed/aggregated.csv`
- Feed archive: `/data/archive/feed/YYYY-MM-DD.csv`

`aggregated.csv` is the live rolling feed consumed by DeltaScout.
The feed archive is append-only historical storage used by the research layer.

CSV header:

`Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice`

### Column meanings

- **Timestamp** - aggregation timestamp (`YYYY-MM-DD HH:MM:SS`)
- **Trades** - number of trades in the interval
- **TotalQty** - total traded quantity
- **AvgSize** - `TotalQty / Trades`
- **BuyQty** - quantity attributed to buy aggressor trades
- **SellQty** - quantity attributed to sell aggressor trades
- **AvgPrice** - quantity-weighted average price
- **ClosePrice** - last trade price observed in the interval
- **HiPrice** - highest trade price observed in the interval
- **LowPrice** - lowest trade price observed in the interval

## Feed contract

- The current canonical feed schema is 10 columns.
- Live feed and feed archive use the same schema.
- Older 8-column files existed before `HiPrice` and `LowPrice` were added.
- The implementation includes a backward-safe migration path for older `aggregated.csv` files so mixed-width rows are not produced.

## Configuration

Current implementation uses constants defined in the script:

- `AGG_INTERVAL` (default: `60`)
- `MAX_RECORDS` (default: `1500`)

## Quick demo

Requirements: Docker Desktop

```powershell
docker compose -f .\docker-compose.demo.yml up -d
.\demo_aggregator.ps1
```

Stop:

```powershell
docker compose -f .\docker-compose.demo.yml down
```

Manual check:

```powershell
Get-Content .\data\feed\aggregated.csv -Tail 5
Get-Content .\data\archive\feed\$(Get-Date -Format yyyy-MM-dd).csv -Tail 5
Get-Content .\data\logs\trades_log.txt -Tail 10
```

Install / run without Docker:

```powershell
pip install websocket-client
python aggregator.py
```
