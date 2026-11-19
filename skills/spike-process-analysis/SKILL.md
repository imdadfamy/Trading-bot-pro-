# Spike Process Analysis

Version: 0.2.0
Owner: quant agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Characterise the spike process of Boom, Crash, DEX and Jump indices (rate, direction, size) and decide whether the time since the last spike carries any information.

## Sources
Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility level are generated independently and do not move in sync; historical patterns do not predict the next move). Independent research repository Orphy123/deriv-research (README read 19 Nov 2026; MIT licence, small, self-published): a pre-registered Post-Spike Drift Capture hypothesis was falsified on Boom 1000 and Crash 1000 and a drift-regime filter was killed at its autocorrelation gate. Its conclusion: no exploitable structure after costs on those two contracts. MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a holdout evaluated several times. Treat as a hypothesis to test, never as proof.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"features.spikes (count, mean interval in bars, bars since last spike, median and p90 spike move), closed candles, family"}}`

## JSON output
`{"cycle_id":"string","skill":"spike-process-analysis","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Spikes are bars whose close-to-close move is at least 5 times the median absolute move of the previous 100 bars, in the direction of the family (Boom up, Crash down). Use features.spikes: the mean interval is the average spacing, bars_since_last_spike is only a description. Waiting time between spikes is geometric if the process is memoryless: its coefficient of variation is close to the square root of (1 - p).

## Evidence
Measured 19 Nov 2026 on 50,000 M1 bars of the demo account. Boom 1000: 2,301 spikes flagged, mean 21.7 bars apart, coefficient of variation 0.996 (a memoryless process gives 0.977), Kolmogorov-Smirnov p = 0.25, spike hazard after a short wait 0.0469 versus 0.0454 after a long wait. Crash 1000: 2,398 spikes, mean 20.8 bars, variation 0.950 (0.976), p = 0.67, hazard 0.0470 versus 0.0493. Median spike about 0.107% of price, 90th percentile about 0.21%, roughly nine times the average one-minute bar range. Conclusion: consistent with a memoryless process; a spike is never 'due'.

## Decision rules
Never argue that a spike is overdue or imminent from elapsed time. Direction between spikes: Boom drifts down and Crash drifts up in small steps, so holding against the spike direction bleeds until the spike, and holding with it risks nothing special except the cost. Vote BUY or SELL only when the measured features support a specific, stated hypothesis and costs (spread as a share of typical bar range) are small; otherwise WAIT. Report the spike rate, the interval statistics and the sample size in the rationale.

## Limits
Bars aggregate ticks: several spikes in one bar count once and a spike across two bars is split. At least 30 spikes are needed. A rate describes the past and is not a forecast. Only Boom and Crash 1000 were measured here; other contracts need their own measurement.

## Positive example
Boom 1000 with 40 flagged spikes in the window, features complete, spread small relative to the bar range: the rationale cites the interval statistics, states that elapsed time is uninformative, and still returns WAIT because no edge is shown.

## Negative example
'No spike for 50 bars, so a spike is due, BUY Boom' is invalid: the hazard is flat. Fewer than 30 spikes in the sample also gives WAIT.

## Abstention
WAIT on missing features, unknown family, fewer than 30 spikes, or any claim that rests on elapsed time since the last spike.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
