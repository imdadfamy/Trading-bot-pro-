# Synthetic Risk Sizing

Version: 0.2.0
Owner: risk agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Size a position from the money at risk, the real stop distance and the contract rules, and reject what the minimum lot cannot respect.

## Sources
Project risk engine and MetaTrader 5 order checks on the demo account, 18 Nov 2026; Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility level are generated independently and do not move in sync; historical patterns do not predict the next move).

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"equity, risk fraction, stop distance, tick size and value, volume min/step/max, features.spikes"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-risk-sizing","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Volume = risk money / (stop distance in ticks times tick value plus costs), rounded down to the step; reject if below the minimum lot. On the adverse side of Boom and Crash replace the stop distance by max(stop, p90 spike) for the risk calculation. Never increase size to recover a loss.

## Evidence
Contract data read on the demo account, 21 Nov 2026 (equity about 10,000 USD, leverage 1000). Money moved by one lot for a price move of one unit: every synthetic index below is 1 dollar (contract size 1); XAUUSD is 100 dollars. So a minimum lot of 0.2 on Boom or Crash risks 0.2 dollar per price unit, a hundred times less than 0.2 lot of gold. Minimum lot, minimum stop distance (broker level plus spread), median spread: Volatility 10 0.5 lot, 0.91, 0.19; Boom 500 0.2 lot, 1.70, 0.53; Crash 500 0.2 lot, 1.25, 0.32; Drift Switch 10 0.1 lot, 6.3, 1.29; Drift Switch 20 0.1 lot, 5.3, 0.32; Drift Switch 30 0.1 lot, 15.2, 5.18; XAUUSD 0.01 lot, 0.79, 0.59. At 0.5% risk (about 50 dollars) a Boom 500 stop of 12 price units allows about 4 lots, far above the minimum lot: the minimum lot is never the binding constraint with realistic stops. The broker's order check accepted a minimal buy and sell on all seven instruments. Minimum order margins: Boom 500 about 2.82, Crash 500 1.39, Volatility 10 0.49. The supervised demo order on Volatility 75 used 0.01 lot with a stop of about 364 points and lost 0.72 dollars after about a minute.

## Decision rules
Volume = money at risk divided by (stop distance times money per price unit per lot): the same risk gives a large lot on a synthetic index and a small lot on gold, and that is correct. The stop is the largest of the volatility stop, ten spreads (so the spread costs at most 0.1 R) and, on Boom and Crash, the 90th-percentile spike. On the side a spike runs against, size as if half a stop more could be lost. Do not refuse an instrument for its lot size; refuse only when the cost in R is above 0.1 or the risk engine says so. Never propose more than the engine's per-trade risk and never increase size after a loss.

## Limits
Margins and minimum lots are contract values read once and can change; the engine, not the model, decides the final volume.

## Positive example
'Minimum lot 0.2 risks 3% with the real stop; above the limit, WAIT.'

## Negative example
Recommending a larger lot after losses is invalid.

## Abstention
WAIT when contract data is missing or the minimum lot breaks the risk limit.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
