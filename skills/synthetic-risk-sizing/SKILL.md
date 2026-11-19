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
Minimum order margins measured by order_check on the demo account: Boom 500 about 2.82, Crash 500 1.42, Volatility 75 0.39. Boom and Crash have a minimum lot of 0.2 on the contracts checked, so the risk per trade can be above the engine limit and the order is then rejected, not reduced. The supervised demo order on Volatility 75 used the minimum lot 0.01 with a stop of about 364 points and lost 0.72 dollars after about a minute.

## Decision rules
Say in the rationale when the minimum lot already exceeds the risk limit; then vote WAIT. Never propose more than the engine's per-trade risk.

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
