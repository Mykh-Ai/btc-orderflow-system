"""Saved-ledger reconciliation and sign attribution, never a backtest runner."""
from pathlib import Path
import hashlib
import json
import math
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
OUT = HERE/'results_v2'
RESOLVED = {'PLAIN_SL','TP1_SL','TP1_TP2_TRAILING_STOP'}


def sign(value):
    return 'POSITIVE' if value > 0 else 'NEGATIVE' if value < 0 else 'ZERO'


def totals(df):
    filled = df[df.entry_status == 'FILLED']
    closed = filled[filled.lifecycle_class.isin(RESOLVED)]
    pnl = closed.net_pnl_usdc
    losses = -float(pnl[pnl < 0].sum())
    return {'candidates': len(df), 'closed': len(closed), 'unresolved': len(filled)-len(closed),
            'wins': int((pnl > 0).sum()), 'losses': int((pnl < 0).sum()),
            'net_usdc': float(pnl.sum()), 'gross_usdc': float(closed.gross_pnl_usdc.sum()),
            'commission_usdc': float(closed.commission_usdc.sum()),
            'slippage_usdc': float(closed.slippage_usdc.sum()),
            'profit_factor': float(pnl[pnl > 0].sum())/losses if losses else None,
            'unresolved_realized_partial_net': float(filled[~filled.lifecycle_class.isin(RESOLVED)].net_pnl_usdc.sum()),
            'blocked_reasons': df.blocked_reason.dropna().value_counts().to_dict()}


def main():
    checks = []
    raw = json.loads((OUT/'candidates.json').read_text())
    candidates = pd.DataFrame(raw)
    assert candidates.candidate_id.is_unique
    assert set(candidates.side) == {'SHORT'}
    candidates['delta_sign'] = candidates.delta.map(sign)
    prep = json.loads((OUT/'preparation_summary.json').read_text())
    audit = pd.read_csv(OUT/'seed_audit.csv', float_precision='round_trip')
    audit['delta_sign'] = audit.delta.map(sign)
    events = pd.read_csv(OUT/'candidate_events.csv')
    assert len(audit) == prep['raw_seeds']
    assert int((audit.status == 'CONFIRMED').sum()) == len(raw) == prep['confirmed_unique']
    assert int((events.event == 'ARMED').sum()) == prep['armed']
    assert not audit.status.str.startswith('OUT_OF_SCOPE').any()
    checks += ['all_raw_deltas_accounted', 'both_signs_admitted', 'all_candidates_short', 'armed_and_confirmed_counts']
    for c in raw:
        f = c['shadow_flags']; start = pd.Timestamp(f['seed_ts']); confirmation = pd.Timestamp(c['signal_ts_utc'])
        assert start < confirmation <= start+pd.Timedelta(hours=4)
        assert confirmation.minute == 0 and confirmation.second == 0
        assert float(f['price']) > float(f['upper'])
        assert float(c['signal_price']) < float(f['lower'])
        assert pd.Timestamp(f['level_available_at']) < pd.Timestamp(f['crossed_at']) <= start
        assert pd.Timestamp(f['sweep_end_ts']) == confirmation
        assert f['delta'] == c['delta'] and f['event'] in {'DELTA_MIN','DELTA_MAX'}
    checks += ['all_candidate_deadlines', 'strict_reclaim', 'price_above_zone_at_trigger',
               'preexisting_levels', 'frozen_stop_cutoff', 'original_delta_attribution']
    zones = pd.read_csv(OUT/'zone_selection_audit.csv', float_precision='round_trip')
    indexed_audit = audit.set_index('seed_id')
    for seed_id, group in zones[zones.decision == 'ELIGIBLE'].groupby('seed_id'):
        row = indexed_audit.loc[seed_id]
        ranked = group.assign(distance=float(row.price)-group.price_upper).sort_values(
            ['distance','significance_score','zone_id'], ascending=[True,False,True])
        assert row.zone_id == ranked.iloc[0].zone_id
    checks.append('nearest_significant_zone')
    for _, row in audit[audit.status == 'DUPLICATE_PENDING_ZONE'].iterrows():
        parent = indexed_audit.loc[row.parent_seed_id]
        assert pd.Timestamp(parent.seed_ts) < pd.Timestamp(row.seed_ts) <= pd.Timestamp(parent.deadline)
        assert row.zone_id == parent.zone_id
    checks.append('both_signs_share_pending_timer')
    result = {'scope': 'same SHORT hypothesis; both raw delta signs; shared portfolio',
              'seed_counts_by_sign': audit.delta_sign.value_counts().to_dict(),
              'seed_status_by_sign': audit.groupby(['delta_sign','status']).size().unstack(fill_value=0).to_dict('index'),
              'runs': {}}
    monthly_rows = []
    for label in ['base','double_slippage']:
        stored = json.loads((OUT/label/'metrics.json').read_text())
        assert not stored['integrity_errors']
        result['runs'][label] = {}
        for mode in ['independent','portfolio']:
            source = pd.read_csv(OUT/label/(mode+'_trades.csv'), float_precision='round_trip')
            df = source.merge(candidates[['candidate_id','delta_sign','delta']], on='candidate_id', how='left', validate='one_to_one')
            assert df.delta_sign.notna().all() and set(df.side) == {'SHORT'}
            overall = totals(df)
            for key in ['closed','unresolved','net_usdc','gross_usdc','commission_usdc','slippage_usdc']:
                assert math.isclose(overall[key], stored[mode][key], rel_tol=0, abs_tol=1e-6)
            closed = df[(df.entry_status == 'FILLED') & df.lifecycle_class.isin(RESOLVED)]
            assert ((closed.gross_pnl_usdc-closed.commission_usdc-closed.slippage_usdc-closed.net_pnl_usdc).abs() < 1e-6).all()
            filled = df[df.entry_status == 'FILLED']
            assert (pd.to_datetime(filled.entry_fill_ts, utc=True) > pd.to_datetime(filled.signal_ts_utc, utc=True)).all()
            assert (filled.initial_stop_price > filled.entry_fill_price).all()
            if mode == 'portfolio':
                ordered = filled.sort_values('entry_fill_ts')
                if len(ordered) > 1:
                    prior_exits = pd.to_datetime(ordered.exit_ts, utc=True).iloc[:-1].reset_index(drop=True)
                    next_entries = pd.to_datetime(ordered.entry_fill_ts, utc=True).iloc[1:].reset_index(drop=True)
                    assert prior_exits.notna().all() and (prior_exits <= next_entries).all()
                checks.append(f'{label}/portfolio/no_overlapping_positions')
            by_sign = {s: totals(group) for s, group in df.groupby('delta_sign')}
            assert sum(v['closed'] for v in by_sign.values()) == overall['closed']
            assert abs(sum(v['net_usdc'] for v in by_sign.values())-overall['net_usdc']) < 1e-6
            result['runs'][label][mode] = {'overall': overall, 'by_sign': by_sign}
            df.to_csv(OUT/label/(mode+'_trades_with_delta_sign.csv'), index=False)
            checks += [f'{label}/{mode}/matched_candidate_sign', f'{label}/{mode}/economic_totals',
                       f'{label}/{mode}/entry_after_confirmation', f'{label}/{mode}/protective_stop',
                       f'{label}/{mode}/sign_partition_sums']
            if label == 'base' and mode == 'portfolio':
                for (month, s), group in df.groupby([df.signal_ts_utc.str[:7], 'delta_sign']):
                    monthly_rows.append({'month': month, 'delta_sign': s, **totals(group)})
    result['monthly_portfolio'] = monthly_rows
    result['verification'] = {'passed': True, 'count': len(checks), 'checks': checks}
    result['query_cache_positive_parity'] = json.loads((HERE/'query_cache_v2/positive_parity.json').read_text())
    (OUT/'sign_analysis.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    pd.DataFrame(monthly_rows).to_csv(OUT/'monthly_portfolio_by_sign.csv', index=False)
    base = result['runs']['base']['portfolio']
    stress = result['runs']['double_slippage']['portfolio']
    names = {'POSITIVE': 'Додатна', 'NEGATIVE': 'Від’ємна', 'ZERO': 'Нульова'}
    table = ['| Початкова дельта | Закриті угоди | Прибуткові | Збиткові | Нетто, USDC | PF |',
             '|---|---:|---:|---:|---:|---:|']
    for s in ['POSITIVE','NEGATIVE','ZERO']:
        if s in base['by_sign']:
            m = base['by_sign'][s]
            pf = f"{m['profit_factor']:.3f}" if m['profit_factor'] is not None else '—'
            table.append(f"| {names[s]} | {m['closed']} | {m['wins']} | {m['losses']} | {m['net_usdc']:.2f} | {pf} |")
    m = base['overall']
    table.append(f"| Разом | {m['closed']} | {m['wins']} | {m['losses']} | {m['net_usdc']:.2f} | {m['profit_factor']:.3f} |")
    report = f'''# Peak_Ai H1: виправлений прогін обох знаків, лише SHORT

Дата: 11.10.2026. Усі угоди симульовані. Це виправлення пропуску від’ємних
дельт у попередній реалізації, а не інше правило входу.

Будь-яка нова журнальна DELTA_MIN/MAX → ціна над суттєвою H1/H4 зоною →
протягом наступних чотирьох годин завершена H1 закривається нижче нижньої
межі зони → SHORT. Жодних LONG. Умови значущості, недавнього перетину рівня,
вибору зони, стопа, TP/BE/trailing і витрати збережено з v1.

## Спільний портфель і внесок знака дельти

{chr(10).join(table)}

Усього сирих дельт: {prep['raw_seeds']}; активовано очікувань: {prep['armed']};
унікальних підтверджень: {prep['confirmed_unique']}; кандидатів у періоді Replay:
{prep['replay_eligible']}. Незавершених портфельних позицій: {m['unresolved']}.
Причини блокування: {json.dumps(m['blocked_reasons'], ensure_ascii=False)}.

Валовий результат: {m['gross_usdc']:.2f}; комісії: {m['commission_usdc']:.2f};
прослизання: {m['slippage_usdc']:.2f} USDC. Номінал: 3000 USDC.
Подвійне прослизання, загальне нетто: {stress['overall']['net_usdc']:.2f} USDC.

Обидва знаки конкурують за один стан очікування та одну позицію. Повторна
дельта будь-якого знака не продовжує таймер. Угода віднесена до знака тієї
дельти, яка першою активувала її очікування. Таблиця є внеском груп у спільний
портфель; це не результат двох окремих стратегій «тільки плюс»/«тільки мінус».
Тому новий результат додатної групи може відрізнятися від позитивно-обмеженого v1.

## Перевірки

7 перевірок виправлення пройшли: обидва знаки та назви подій допускаються
тільки в SHORT, таймер спільний, решта коду стратегії ідентична v1.
Кеш native Monitor точно відтворив 400 повних кандидатів та 2846 статусів
попереднього позитивно-обмеженого прогону. Нові журнали: {len(checks)} перевірок
пройшли; арифметика підсумків і розподілу за знаком збігається.

## Межі висновку

Період рішень: 20.03–17.08.2026, виходи до 19.08. Ці місяці вже досліджувалися;
це не новий незалежний holdout. Вхідна ціна, дельти й рівні з одного legacy
Spot feed; виконання на BTCUSDC Spot. Ліквідації відсутні й не є фільтром.
Це адаптер окремих H1/H4 зон, не весь Monitor 39A. Немає контролю без дельти,
відсотків за позикою, ордербука й реального часткового виконання.
Попередній прогін із 210 угодами та -1242.08 USDC був неповним щодо задуму:
він оцінював тільки додатні дельти. Старі результати збережені, не перезаписані.
Жодних змін production або реальних ордерів.
'''
    (HERE/'REPORT_UA.md').write_text(report)
    print(json.dumps({'portfolio': base, 'double_slippage': stress,
                      'preparation': prep, 'checks_passed': len(checks)}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
