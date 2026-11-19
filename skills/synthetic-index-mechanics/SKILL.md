# Synthetic Index Mechanics

Version: 0.2.0
Owner: quant agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Identify the family of a synthetic index from its symbol and state what is random by construction, so that only meaningful questions are asked of the data.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): simulated, open 24/7, no order book, news does not affect prices, notable historical patterns can be chance. Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility level are generated independently and do not move in sync; historical patterns do not predict the next move).

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"symbol, closed candles, features"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-index-mechanics","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Map the symbol to a family: Volatility (constant volatility; ticks every 2 s or every 1 s), Boom and Crash (spike on average every N ticks, N in the name, up for Boom and down for Crash), Drift Switch, DEX, Jump, Step, Range Break, Flip and Volatility Boom/Crash variants. Volatility 10 and Volatility 10 (1s) are independent series. Only measure what the family can show: news, order flow and sessions have no meaning here.

## Evidence
Verified on the project's demo account: Boom shows only upward spikes and Crash only downward ones; Volatility 75 returns are symmetric; Boom and Crash waiting times between spikes behave like a memoryless process (see spike-process-analysis); Volatility 10 and Volatility 10 (1s) both exist and carry different spreads (0.162 and 0.33). Symbols available include Boom/Crash 50 to 1000, Boom/Crash Flip, Volatility Boom/Crash 400/550/750 and Drift Switch Index 10/20/30.

## Decision rules
Do not use news, sessions or macro arguments for these symbols. Name the family and the number in the symbol in the rationale. Unknown family: WAIT.

## Limits
Mechanics come from the provider's description and may change; a measured invariant on a short sample is evidence, not proof.

## Positive example
'Crash 500: downward spikes by construction, drift upward between spikes; no news channel; judging only price features.'

## Negative example
Quoting a US announcement as a reason to trade Boom is invalid.

## Abstention
WAIT on an unknown family or insufficient sample.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
