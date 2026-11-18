# Synthetic Risk Sizing

Version: 0.1.0  
Owner: risk agent  
Scope: synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step)  
Status: research specification; no validated trading edge  
Licence: original project documentation, no third-party code included.

## Objective
Size and veto trades on synthetic indices given their unusual contract limits and spike risk.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states that there is no order book, that any notable historical pattern is purely chance, and that external news does not affect these prices.

## Preconditions
UTC timestamps, broker and symbol identity, a known synthetic-index family, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.1.0","inputs":{"description":"equity, risk_fraction, stop_distance, contract_metadata (point value, volume min/max/step, stops level, margin), spike_size_estimate"}}`

## JSON output
`{"cycle_id":"string","skill":"synthetic-risk-sizing","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Compute the volume that risks the configured fraction, round DOWN to the step, and veto if the minimum volume already exceeds the risk budget (for example 0.2 lot on Boom and Crash). Add the typical spike size to the stop distance when estimating the worst loss, because a spike can gap through a stop. Check margin and the maximum volume; refuse positions that could be held across a rollover without accounting for the swap.

## Evidence so far
On the demo account Boom 500 and Crash 500 require a minimum of 0.2 lot and stops of about 1,000 points or more, so the minimum risk per trade can exceed a small risk budget.

## Limits
Stops on these markets are not protected against spikes; actual loss can exceed the planned risk. Point value must come from the broker's tick value and tick size, not from assumptions. This specification has no calibrated probability or verified economic edge. Scores are qualitative.

## Positive example
A fresh, complete sample of a known family yields a traceable report with the measured statistic, its confidence interval, the sample size and a UTC cycle ID; even a directional report cannot bypass the risk engine.

## Negative example
Unknown family, too few observations, a pattern that does not beat the random-entry null, or a stale quote yields WAIT and a reason.

## Abstention
WAIT on missing data, unknown family, insufficient sample size (fewer than 30 events), significance not reached after correction for the number of tests, or conflicting evidence.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. Implementation pending validation.
