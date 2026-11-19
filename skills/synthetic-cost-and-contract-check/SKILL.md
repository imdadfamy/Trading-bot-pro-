# Synthetic Cost and Contract Check

Version: 0.2.0
Owner: risk agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Check that costs (spread, slippage, commission) are small relative to the move the idea needs, using the instrument's measured contract data.

## Sources
MetaTrader 5 contract data and bar spreads read from the project's Deriv demo account (read-only), 19 Nov 2026. MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a holdout evaluated several times. Treat as a hypothesis to test, never as proof.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"features.spread, features.spread_to_atr, stop distance, target distance, minimum lot, contract size"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-cost-and-contract-check","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Compute the round-trip cost as one spread plus assumed slippage and commission. Compare it with the stop distance (cost in R = cost / stop) and with the target. An idea whose cost exceeds about 10% of its stop (0.1 R) loses a tenth of every trade before it starts. Bars are bid-built: a buy pays the full spread on entry.

## Evidence
Measured median bar spread: Boom 1000 0.152 on a price near 14,940 (about 9% of the average M1 bar range 1.73); Crash 1000 0.060 on 5,765 (about 9% of an average range 0.70); Volatility 10 (2s) 0.162 and Volatility 10 (1s) 0.33 on H4 bars with prices near 6,000 (about 2% of a median H1 bar range of 7.8 and 15.4 respectively). One real demo order on Volatility 75 cost a spread of 13.7 on a 38,900 price. Commissions: none charged on the one measured order.

## Decision rules
State the cost in R in the rationale. If cost / stop exceeds 0.1, vote WAIT unless the target is at least ten times the cost. Never ignore the spread because bars look profitable on closes alone.

## Limits
Spread is a bar statistic, not tick-by-tick; slippage and commission were measured on a single order. Contract values can change.

## Positive example
Volatility 10 H1, spread 2% of the stop: cost 0.02 R, acceptable; says so and moves on to the directional question.

## Negative example
An M1 idea on Boom 1000 with a stop of one bar range: spread is 9% of the stop and a spike can jump it, so WAIT.

## Abstention
WAIT when spread or contract data are missing or when cost exceeds 10% of the stop.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
