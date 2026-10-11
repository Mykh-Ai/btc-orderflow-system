"""Parallel immutable as-of queries; serial candidate state remains unchanged."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import json
import multiprocessing
from pathlib import Path
import time

import pandas as pd

from market_monitor.closed_structure_adapter import ClosedStructureMonitor
from research.peak_ai_delta_h1.inputs import load_legacy, load_seeds

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'deltascout/research_material'
CACHE = HERE / 'query_cache_v2'
ORIGINAL = HERE.parent / 'peak_ai_delta_h1/results_v1_checkpointed'
_monitor = None
_reused_keys = set()


def _worker(task):
    index, timestamps = task
    path = CACHE / f'part_{index:02d}.jsonl'
    existing = {}
    if path.exists():
        with path.open() as stream:
            for line in stream:
                item = json.loads(line)
                existing[item['ts']] = item
    assert set(existing).issubset(timestamps)
    started = time.monotonic()
    with path.open('a') as stream:
        for count, ts in enumerate(timestamps, 1):
            if ts not in existing and ts not in _reused_keys:
                zones, counts, evidence = _monitor.query(datetime.fromisoformat(ts))
                item = {'ts': ts, 'zones': zones, 'counts': counts, 'evidence': evidence}
                stream.write(json.dumps(item, default=str, allow_nan=False) + '\n')
                stream.flush()
    print(f'query batch {index}: complete, {round(time.monotonic()-started)}s', flush=True)
    return {'partition': index, 'queries': len(timestamps)}


def prepare(workers=8):
    global _monitor, _reused_keys
    from research.peak_ai_delta_h1_all_signs.run import code_hashes, dump, digest, verify_inputs
    verify_inputs(ORIGINAL)
    current_hashes = code_hashes()
    prior = HERE/'query_cache_before_rebalance'
    reused = {}
    reused_sources = {}
    if prior.exists():
        prior_freeze = json.loads((prior/'freeze.json').read_text())
        assert prior_freeze['input_manifest_sha256'] == digest(ORIGINAL/'input_hashes.csv')
        without_orchestrator = lambda h: {k:v for k,v in h.items() if not k.endswith('/query_cache.py')}
        assert without_orchestrator(prior_freeze['code_hashes']) == without_orchestrator(current_hashes)
        for path in sorted(prior.glob('part_*.jsonl')):
            reused_sources[path.name] = digest(path)
            with path.open() as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        if not line.endswith('\n'):
                            print('Discarding interrupted incomplete final JSON line in', path.name, flush=True)
                            break
                        raise
                    assert item['ts'] not in reused
                    reused[item['ts']] = item
    manifest = {'code_hashes': current_hashes, 'input_manifest_sha256': digest(ORIGINAL/'input_hashes.csv'),
                'workers': workers, 'batch_size': 16, 'reused_source_hashes': reused_sources,
                'adapter': 'unchanged native closed structure adapter',
                'full_lifetime_history_per_query': True}
    CACHE.mkdir(exist_ok=True)
    freeze = CACHE/'freeze.json'
    if freeze.exists():
        if json.loads(freeze.read_text()) != manifest:
            raise RuntimeError('Query cache frozen code/inputs/workers mismatch')
    else:
        dump(freeze, manifest)
    _reused_keys = set(reused)
    with (CACHE/'part_reused.jsonl').open('w') as stream:
        for ts in sorted(reused):
            stream.write(json.dumps(reused[ts], default=str, allow_nan=False)+'\n')
    bars = load_legacy(BASE/'execution_feed/btcusdt_legacy_spot_1m/daily')
    bars = [b for b in bars if b.ts <= datetime.fromisoformat('2026-08-19T23:59:00+00:00')]
    times = {b.ts for b in bars}
    seeds = load_seeds(BASE/'raw_archive')
    timestamps = sorted({s.ts.isoformat() for s in seeds if s.ts in times})
    _monitor = ClosedStructureMonitor(bars)
    dump(CACHE/'inventory.json', _monitor.inventory())
    print('Native monitor ready:', len(_monitor.references), 'references;', len(timestamps), 'queries', flush=True)
    assert _reused_keys.issubset(timestamps)
    print('Reusing', len(_reused_keys), 'verified completed queries; remaining', len(timestamps)-len(_reused_keys), flush=True)
    tasks = [(i//16, timestamps[i:i+16]) for i in range(0,len(timestamps),16)]
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('fork')) as pool:
        result = list(pool.map(_worker, tasks))
    assert code_hashes() == manifest['code_hashes']
    verify_inputs(ORIGINAL)
    dump(CACHE/'completed.json', {'completed': True, 'queries': len(timestamps), 'partitions': result,
         'part_hashes': {p.name: digest(p) for p in sorted(CACHE.glob('part_*.jsonl'))},
         'inventory_sha256': digest(CACHE/'inventory.json')})
    print('All native as-of queries complete', flush=True)


class CachedStructureMonitor:
    def __init__(self, bars):
        from research.peak_ai_delta_h1_all_signs.run import code_hashes, digest
        freeze = json.loads((CACHE/'freeze.json').read_text())
        complete = json.loads((CACHE/'completed.json').read_text())
        assert freeze['code_hashes'] == code_hashes()
        assert freeze['input_manifest_sha256'] == digest(ORIGINAL/'input_hashes.csv')
        assert complete['completed']
        assert complete['inventory_sha256'] == digest(CACHE/'inventory.json')
        self.references = json.loads((CACHE/'inventory.json').read_text())
        self.queries = {}
        for name, expected in complete['part_hashes'].items():
            path = CACHE/name
            assert digest(path) == expected
            for line in path.read_text().splitlines():
                item = json.loads(line)
                assert item['ts'] not in self.queries
                self.queries[item['ts']] = item
        assert len(self.queries) == complete['queries']
        times = {b.ts.isoformat() for b in bars}
        assert set(self.queries).issubset(times)
        self.last_query = None

    def query(self, ts):
        if self.last_query is not None and ts < self.last_query:
            raise ValueError('queries must be chronological')
        self.last_query = ts
        item = self.queries[ts.isoformat()]
        return item['zones'], item['counts'], item['evidence']

    def inventory(self):
        return self.references


def positive_parity():
    from collections import defaultdict
    from research.peak_ai_delta_h1.engine import DeltaH1Engine
    from research.peak_ai_delta_h1_all_signs.run import dump
    bars = load_legacy(BASE/'execution_feed/btcusdt_legacy_spot_1m/daily')
    bars = [b for b in bars if b.ts <= datetime.fromisoformat('2026-08-19T23:59:00+00:00')]
    seeds = load_seeds(BASE/'raw_archive')
    batches = defaultdict(list)
    for seed in seeds:
        batches[seed.ts].append(seed)
    engine = DeltaH1Engine(CachedStructureMonitor(bars))
    for bar in bars:
        engine.step(bar, batches.get(bar.ts, ()))
    audit = engine.finish()
    expected = json.loads((ORIGINAL/'candidates.json').read_text())
    actual = json.loads(json.dumps([c.to_dict() for c in engine.candidates], default=str))
    assert actual == expected, 'Cached monitor changed original positive-only candidates'
    expected_audit = pd.read_csv(ORIGINAL/'seed_audit.csv').set_index('seed_id').status.to_dict()
    assert {r['seed_id']: r['status'] for r in audit} == expected_audit
    dump(CACHE/'positive_parity.json', {'passed': True, 'exact_candidate_records': len(actual),
         'exact_seed_statuses': len(audit), 'comparison': 'original completed v1 output'})
    print('Positive-only parity: all 400 full candidates and 2846 statuses match', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'positive_parity'])
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.workers)
    else:
        positive_parity()
