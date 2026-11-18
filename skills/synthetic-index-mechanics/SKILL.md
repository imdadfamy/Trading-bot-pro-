# Synthetic Index Mechanics

Version: 0.1.0  
Owner: quant agent  
Scope: synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step)  
Status: research specification; no validated trading edge  
Licence: original project documentation, no third-party code included.

## Objective
Identify the family of a synthetic index from its symbol and state what is random BY CONSTRUCTION, so that only meaningful questions are asked of the data.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states that there is no order book, that any notable historical pattern is purely chance, and that external news does not affect these prices.

## Preconditions
UTC timestamps, broker and symbol identity, a known synthetic-index family, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.1.0","inputs":{"description":"symbol, broker, closed_candles (UTC, bid/ask), contract_metadata (tick size, volume limits)"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-index-mechanics","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Map the symbol to a family (Volatility, Boom, Crash, Drift Switching, DEX, Jump, Step, Range Break, other). List the family's documented invariants and verify each on the sample: Step moves are exactly +-step; Volatility returns have stable standard deviation; Boom has only upward spikes and Crash only downward ones; Jump spikes are symmetric. Report which hypotheses remain admissible (for example a drift between spikes) and which are excluded by construction (news impact, order-flow patterns). State the sample size behind every verdict.

## Evidence so far
On 17 days of M5 bars of the demo account: Boom 500 showed 757 upward moves above 0.1% and none downward; Crash 500 the reverse; Volatility 75 was symmetric (1,635 up, 1,657 down).

## Limits
Mechanics come from the provider's public description and can change; a measured invariant on a short sample is evidence, not proof. Unknown families must not be guessed: answer WAIT. This specification has no calibrated probability or verified economic edge. Scores are qualitative.

## Positive example
A fresh, complete sample of a known family yields a traceable report with the measured statistic, its confidence interval, the sample size and a UTC cycle ID; even a directional report cannot bypass the risk engine.

## Negative example
Unknown family, too few observations, a pattern that does not beat the random-entry null, or a stale quote yields WAIT and a reason.

## Abstention
WAIT on missing data, unknown family, insufficient sample size (fewer than 30 events), significance not reached after correction for the number of tests, or conflicting evidence.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. Implementation pending validation.
