# Boom and Crash Stop Gap Risk

Version: 0.2.0
Owner: risk agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Measure how far a stop can be jumped by a spike so that risk is judged on the possible loss, not on the requested stop distance.

## Sources
Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility level are generated independently and do not move in sync; historical patterns do not predict the next move). MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a holdout evaluated several times. Treat as a hypothesis to test, never as proof.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"features.spikes (p90 spike move), features.atr_14, spread, stop distance, side, family"}}`

## JSON output
`{"cycle_id":"string","skill":"boom-crash-stop-gap-risk","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
A stop is a trigger, not a guaranteed price: after a spike the order fills at the first available price. The adverse side is a sell on Boom (up spikes) and a buy on Crash (down spikes). Compare the planned stop distance with the median and 90th-percentile spike moves; an effective risk multiple is max(stop, spike move) / stop on the adverse side. The backtest cost model fills stops at the adverse extreme of a spike bar ('spike_gap').

## Evidence
Deriv's own worked example: sell Boom at 10,000, stop 10,010, fill 10,025, planned risk $5 and realised loss $12.50 (illustrative, not execution data). AureusAI measured stops hit by spikes filling at the post-spike quote in 13 of 13 cases, mean overshoot 5.0 basis points. Our M1 measurement: median spike 0.107%, p90 0.21% of price, about nine times a typical bar range, so any stop tighter than about nine bar ranges is likely to be jumped on the adverse side.

## Decision rules
On the adverse side with a stop tighter than the p90 spike, the real risk is about p90 spike / stop times the planned risk: say so and vote WAIT unless the position size is cut accordingly. On the favourable side a spike is a gain beyond the target, not a risk. Never recommend widening a stop to 'survive' without reducing size.

## Limits
The overshoot depends on the broker's tick feed; our own order history holds a single trade. Spike sizes were measured on M1 bars of one month for Boom 1000 and Crash 1000.

## Positive example
Sell Boom 1000 with a stop of 2 bar ranges: the rationale notes that the p90 spike is about nine bar ranges, estimates the effective risk at four to five times the plan, and returns WAIT.

## Negative example
'The stop limits my loss to X' on Boom or Crash is invalid without the gap statement.

## Abstention
WAIT when spike statistics are missing or the stop is below the p90 spike on the adverse side.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
