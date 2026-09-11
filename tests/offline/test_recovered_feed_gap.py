from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deltascout.research_bundle.build_recovered_feed_gap import (
    SHI_COLUMNS,
    _legacy_utc_minute,
    build_recovered_feed_gap,
)


def write_rows(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def legacy(ts, close):
    return dict(Timestamp=ts, Trades='10', TotalQty='2', BuyQty='0.5', SellQty='1.5',
                AvgPrice=str(close), ClosePrice=str(close), HiPrice=str(close + 1), LowPrice=str(close - 1))


def shi(ts, close=0, synthetic='1'):
    row = {key: '0' for key in SHI_COLUMNS}
    row.update(Timestamp=ts, Open=str(close), High=str(close), Low=str(close), Close=str(close),
               Volume='0' if synthetic == '1' else '1', IsSynthetic=synthetic,
               OpenInterest='123.45', FundingRate='0.001')
    return row


def build(root, start, end):
    return build_recovered_feed_gap(root/'legacy', root/'shi', root/'out', root/'quality',
                                    datetime.fromisoformat(start), datetime.fromisoformat(end))


def read(path):
    with path.open(encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def test_may4_legacy_local_clock_joins_exact_utc_enrichment(tmp_path):
    write_rows(tmp_path/'legacy/2026-05-04.csv', [legacy('2026-05-04 10:08:00', 79636),
                                               legacy('2026-05-04 12:08:00', 78821)])
    original = shi('2026-05-04 10:09:00', 78830, '0')
    write_rows(tmp_path/'shi/2026-05-04.csv', [shi('2026-05-04 10:08:00'), original])
    result = build(tmp_path, '2026-05-04 10:08:00', '2026-05-04 10:08:00')
    output = read(tmp_path/'out/2026-05-04.csv')
    assert output[0]['Close'] == '78821.00'
    assert output[0]['OpenInterest'] == '123.45'
    assert output[1] == original
    quality = read(result.quality_path)[0]
    assert quality['LegacyTimestamp'] == '2026-05-04 12:08:00'
    assert quality['LegacyUtcOffsetSeconds'] == '7200'
    assert quality['LegacySourceRow'] == '3'
    assert quality['FundingSource'].endswith('untrusted')
    assert quality['LiqSource'] == 'missing_forceOrder_ws_gap'
    manifest = json.loads((tmp_path/'quality/recovery_manifest.json').read_text())
    assert manifest['legacy_source_timezone'] == 'Europe/Bratislava'
    assert len(manifest['inputs']) == 2
    assert all(len(item['sha256']) == 64 for item in manifest['inputs'])


def test_utc_evening_reads_next_local_day_and_audits_missing_minutes(tmp_path):
    write_rows(tmp_path/'legacy/2026-05-07.csv', [legacy('2026-05-07 00:00:00', 81539)])
    write_rows(tmp_path/'shi/2026-05-06.csv', [shi('2026-05-06 22:00:00')])
    result = build(tmp_path, '2026-05-06 22:00:00', '2026-05-06 22:01:00')
    output = read(tmp_path/'out/2026-05-06.csv')
    assert [(r['Timestamp'], r['Close']) for r in output] == [('2026-05-06 22:00:00', '81539.00')]
    assert result.class_counts['MISSING_LEGACY_SOURCE'] == 1
    assert read(result.quality_path)[1]['Timestamp'] == '2026-05-06 22:01:00'


@pytest.mark.parametrize(('source', 'expected', 'offset'), [
    ('2026-05-04 12:07:59', '2026-05-04 10:08:00', 7200),
    ('2026-05-04 12:08:01', '2026-05-04 10:08:00', 7200),
    ('2026-01-04 12:08:00', '2026-01-04 11:08:00', 3600),
])
def test_clock_conversion_uses_dst_and_nearest_minute(source, expected, offset):
    assert _legacy_utc_minute(source, ZoneInfo('Europe/Bratislava')) == (datetime.fromisoformat(expected), offset)


@pytest.mark.parametrize('source', ['2026-03-29 02:30:00', '2026-10-25 02:30:00'])
def test_uncertain_dst_minute_is_rejected(source):
    with pytest.raises(ValueError, match='ambiguous or nonexistent'):
        _legacy_utc_minute(source, ZoneInfo('Europe/Bratislava'))


def test_conflicting_normalized_minutes_fail_before_writing(tmp_path):
    write_rows(tmp_path/'legacy/2026-05-04.csv', [legacy('2026-05-04 12:07:59', 78821),
                                               legacy('2026-05-04 12:08:00', 78830)])
    with pytest.raises(ValueError, match='duplicate normalized'):
        build(tmp_path, '2026-05-04 10:08:00', '2026-05-04 10:08:00')
    assert not (tmp_path/'out').exists()


def test_existing_recovery_artifacts_are_never_overwritten(tmp_path):
    write_rows(tmp_path/'legacy/2026-05-04.csv', [legacy('2026-05-04 12:08:00', 78821)])
    build(tmp_path, '2026-05-04 10:08:00', '2026-05-04 10:08:00')
    path = tmp_path/'out/2026-05-04.csv'
    before = path.read_bytes()
    with pytest.raises(FileExistsError, match='preserve existing'):
        build(tmp_path, '2026-05-04 10:08:00', '2026-05-04 10:08:00')
    assert path.read_bytes() == before
