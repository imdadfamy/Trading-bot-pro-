# Spike Process Analysis

Version: 0.1.0  
Owner: quant agent  
Scope: synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step)  
Status: research specification; no validated trading edge  
Licence: original project documentation, no third-party code included.

## Objective
Characterise the spike process of Boom, Crash, DEX and Jump indices: rate, direction, size and whether the waiting time between spikes is memoryless.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states that there is no order book, that any notable historical pattern is purely chance, and that external news does not affect these prices.

## Preconditions
UTC timestamps, broker and symbol identity, a known synthetic-index family, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.1.0","inputs":{"description":"closed_candles (UTC, OHLC), timeframe, spike_threshold (default 5 times the median absolute bar return of the previous 100 bars)"}}`

## JSON output
`{"cycle_id":"string","skill":"spike-process-analysis","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Flag spike bars with the fixed rule; estimate the rate per bar with a Wilson 95% interval; build the distribution of bars since the previous spike and compare its hazard (probability of a spike given k calm bars) with a constant hazard; test directional asymmetry and the size distribution. A constant hazard means waiting for a spike to be 'due' carries no information.

## Evidence so far
Deriv documents a spike every 500 ticks on average for Boom 500 and Crash 500; per five-minute bar this appears as roughly one bar in seven carrying a large one-sided move in the measured sample.

## Limits
Bars aggregate ticks: several spikes in one bar are counted once and a spike straddling two bars is split. Needs at least 30 spikes, otherwise abstain. The rate is a historical description, not a forecast. This specification has no calibrated probability or verified economic edge. Scores are qualitative.

## Positive example
A fresh, complete sample of a known family yields a traceable report with the measured statistic, its confidence interval, the sample size and a UTC cycle ID; even a directional report cannot bypass the risk engine.

## Negative example
Unknown family, too few observations, a pattern that does not beat the random-entry null, or a stale quote yields WAIT and a reason.

## Abstention
WAIT on missing data, unknown family, insufficient sample size (fewer than 30 events), significance not reached after correction for the number of tests, or conflicting evidence.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. Implementation pending validation.
