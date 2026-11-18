# Synthetic Cost And Contract Check

Version: 0.1.0  
Owner: risk agent  
Scope: synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step)  
Status: research specification; no validated trading edge  
Licence: original project documentation, no third-party code included.

## Objective
Turn a candidate trade on a synthetic index into its true cost and feasibility on the broker's contract, before it reaches the risk engine.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states that there is no order book, that any notable historical pattern is purely chance, and that external news does not affect these prices.

## Preconditions
UTC timestamps, broker and symbol identity, a known synthetic-index family, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.1.0","inputs":{"description":"symbol, bid, ask, bar_range, contract_metadata (volume min/max/step, stops level, filling modes, margin, swaps), planned_holding_time"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-cost-and-contract-check","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Compute the spread as a share of the typical bar move and of the planned stop; verify the minimum stop distance measured from the CLOSING price (bid for a long, ask for a short) as stops level plus spread; verify volume limits and step, the broker's allowed fill mode, margin required and overnight swap if the position can cross the rollover. Express the round-trip cost in R. Veto when the cost exceeds a configured share of the expected reward.

## Evidence so far
Verified with order_check on the demo account: the broker rejected a stop of 0.40 on gold and accepted 0.60, matching stops level (0.20) plus the spread of the moment (0.29).

## Limits
Swaps, commissions and slippage are not exposed by the terminal's Python API and must be read from the contract specification or the provider. Costs are those observed at one moment. This specification has no calibrated probability or verified economic edge. Scores are qualitative.

## Positive example
A fresh, complete sample of a known family yields a traceable report with the measured statistic, its confidence interval, the sample size and a UTC cycle ID; even a directional report cannot bypass the risk engine.

## Negative example
Unknown family, too few observations, a pattern that does not beat the random-entry null, or a stale quote yields WAIT and a reason.

## Abstention
WAIT on missing data, unknown family, insufficient sample size (fewer than 30 events), significance not reached after correction for the number of tests, or conflicting evidence.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. Implementation pending validation.
