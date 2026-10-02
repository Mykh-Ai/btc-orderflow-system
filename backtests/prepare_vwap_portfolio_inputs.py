"""Collect read-only archives and prepare immutable local replay inputs."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'server_journals' / 'vwap_portfolio_2026-09-18'
RESEARCH = Path('D:/Project_V/btc-orderflow-system/deltascout/research_material')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = subprocess.check_output([
        'C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'NUL', 'root@95.216.139.172',
        'tar -czf - -C /root/volume-alert/data/archive deltascout feed',
    ], timeout=60)
    (OUT / 'archive_snapshot.tar.gz').write_bytes(payload)
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive.getmembers():
            target = (OUT / 'archive' / member.name).resolve()
            if not target.is_relative_to((OUT / 'archive').resolve()) or member.issym() or member.islnk():
                raise RuntimeError('unsafe archive member')
        archive.extractall(OUT / 'archive', filter='data')
    official = OUT / 'btcusdc_spot' / 'daily'
    official.mkdir(parents=True, exist_ok=True)
    cache_sources = [
        RESEARCH / 'execution_feed/btcusdc_spot_1m_through_2026-08-31_v1',
        RESEARCH / 'execution_feed/btcusdc_spot_1m_sep2026',
        ROOT / 'server_journals/2026-09-18/btcusdc_spot',
    ]
    for source in cache_sources:
        for path in (source / 'daily').glob('*.csv'):
            destination = official / path.name
            if destination.exists() and destination.read_bytes() != path.read_bytes():
                raise RuntimeError(f'conflicting cached official bars: {path.name}')
            shutil.copy2(path, destination)
        provenance = source / 'provenance'
        if provenance.exists():
            shutil.copytree(provenance, OUT / 'cached_provenance' / source.name, dirs_exist_ok=True)
    # Today has no completed Binance Vision daily archive yet. Public Spot REST
    # klines preserve open labels; exclude the currently forming candle.
    start = int(datetime(2026, 9, 18, tzinfo=timezone.utc).timestamp() * 1000)
    cutoff = int(datetime.now(timezone.utc).timestamp() // 60 * 60000)
    cursor = start
    raw_rows = []
    while cursor < cutoff:
        url = ('https://api.binance.com/api/v3/klines?symbol=BTCUSDC&interval=1m'
               f'&startTime={cursor}&endTime={cutoff-1}&limit=1000')
        with urllib.request.urlopen(url, timeout=30) as response:
            batch = json.load(response)
        if not batch:
            break
        raw_rows.extend(row for row in batch if row[6] < cutoff)
        cursor = batch[-1][0] + 60000
    raw = OUT / 'btcusdc_spot' / 'rest_2026-09-18.json'
    raw.write_text(json.dumps(raw_rows), encoding='utf-8')
    fields = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'BuyQty',
              'SellQty', 'IsSynthetic', 'AggTrades', 'VWAP', 'OpenInterest',
              'FundingRate', 'LiqBuyQty', 'LiqSellQty']
    with (official / '2026-09-18.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in raw_rows:
            volume, buy = float(row[5]), float(row[9])
            writer.writerow(dict(zip(fields, [
                datetime.fromtimestamp(row[0]/1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                *row[1:6], row[9], format(volume-buy, '.8f'), 0, row[8],
                format(float(row[7])/volume, '.8f') if volume else row[4], '', '', '', '',
            ])))
    report = {'collected_at_utc': datetime.now(timezone.utc).isoformat(),
              'server_archive_sha256': hashlib.sha256(payload).hexdigest(),
              'rest_url': 'https://api.binance.com/api/v3/klines',
              'symbol': 'BTCUSDC', 'interval': '1m', 'today_closed_rows': len(raw_rows),
              'rest_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
              'today_cutoff_completed_utc': datetime.fromtimestamp(cutoff/1000, timezone.utc).isoformat(),
              'cache_sources': list(map(str, cache_sources))}
    (OUT / 'collection_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
