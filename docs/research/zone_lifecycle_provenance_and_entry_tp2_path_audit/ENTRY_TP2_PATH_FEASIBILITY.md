# Entry → TP2 ordered structure path feasibility

## Evidence basis and price units

`ENTRY_TP2_PATH_AUDIT.csv` is an exploratory, pre-cutoff enumeration for the same 19 chronology-valid frozen trades. The actual execution entry, TP1 and TP2 are stored in the execution quote currency; significant and registry bounds are market-feed quote prices. We converted execution prices back to market quote using the frozen `quote_conversion_at_entry_approx`, matching the approximation in `snapshot_v2.py:292-304`. This is **approximate** and is not a tick-exact execution-price comparison. No post-cutoff bars or outcomes were used. The CSV has candidate IDs/counts and overlap pairs, not a canonical ordered path.

## What can be enumerated

Snapshot's `_nearest_qualified` considers significant rows with `status` SIGNIFICANT or QUALIFIED, one directional check against current market price, then chooses the minimum nonnegative near-boundary distance and ID (`snapshot_v2.py:202-216`). It does not enumerate every zone on the entry→TP2 interval, enforce one side on significant rows (they have no BUY_SIDE/SELL_SIDE field), or deduplicate overlapping views. `_structure_view` separately retains only one nearest active same-side registry liquidity row (`snapshot_v2.py:271-321`). The underlying pre-cutoff frames contain more rows (`:149-167`), so interval candidates can be counted and approximately sorted by first boundary encountered: for LONG, increasing price from entry to TP2; for SHORT, decreasing. A zone already containing entry intersects the path at entry and cannot be treated as a fresh barrier ahead solely by the selection distance of zero.

The exploratory CSV counts qualified significant intervals intersecting entry→TP2 as 0 in one case, 1 in five, 2 in eleven, and 3 in two. Active same-side registry intervals intersecting the path range from 0 to 9; seven cases have none. This establishes candidate enumeration, not independent market objects. Example `EX_EN_1784376441` has two qualified significant intervals, three same-side active registry intervals, and six significant↔registry overlap pairs on the approximate path. `EX_EN_1788166698` has three, five, and eleven respectively. One registry row can overlap multiple significant rows; geometric overlap is many-to-many. `ENTRY_TP2_PATH_AUDIT.csv` records every enumerated ID, allowing review without inventing a zone.

## Required object fields and present evidence

| Needed for ordered path | Current repository evidence | Limitation |
|---|---|---|
| Stable, provenance-safe ID | Significant and registry IDs exist (`significant_market_zones.py:64-76`; `zone_registry.py:276-285`) | Both are sequential rebuild-local identifiers in Snapshot; no cross-branch common lineage. |
| Type and side | Significant `dominant_zone_types`; registry `zone_type`, `side`, source timeframes (`significant_market_zones.py:149-151,190-201`; `zone_registry.py:284-295`) | Significant type is a mixture of 30-day accumulation sources and has no opposing-side identity. Registry type/side cannot be inherited by it from geometric match. |
| Lower/upper and price order | Both frames retain bounds; conversion in frozen snapshot (`snapshot_v2.py:292-304`) | Many bounds overlap; equal/inside path order is not a unique object order. Conversion is approximate. |
| Distance from entry and in R | Entry, risk and approximate conversion available (`snapshot_v2.py:292-304,390-400`) | Can be computed geometrically but represents a candidate boundary, not necessarily an independent obstacle; market vs execution currency remains approximate. |
| Relation to TP1/TP2 | `_target_relation` evaluates BEFORE/INSIDE/BEYOND for selected zone (`snapshot_v2.py:265-268,298-304`) | Not generated for all rows; overlapping zones can straddle a target. |
| Pre-cutoff lifecycle | Registry rebuild computes fields (`zone_registry.py:547-850`) | No shared identity with significant aggregate; cleared zones removed from liquidity map at latest close and omitted from fresh Snapshot registry (`liquidity_zones.py:128-140,641-659`). |
| Source quality | `data_quality` exists on both rows (`significant_market_zones.py:180-218`; `zone_registry.py:367`) | It attests raw/degraded feed, not common origin or full history. |

## Decision

Architectural answer **C = `PARTIAL`**. The source frames permit a read-only, approximate list of all qualifying **interval candidates** between entry and TP2. They do **not** prove a stable, nonduplicated, lifecycle-bearing path of independent opposing structures. The missing pieces are a source-lineage relationship between accumulation aggregates and structure levels, cross-cutoff stable identities, retention of historically cleared rows, and a defensible rule for many-to-many overlap. This audit does not choose or implement such a rule.
