# Constant Volatility Validation

Version: 0.1.0  
Owner: quant agent  
Scope: synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step)  
Status: research specification; no validated trading edge  
Licence: original project documentation, no third-party code included.

## Objective
Check that a Volatility index behaves as announced (constant nominal volatility, independent returns) before any claim of predictability is entertained.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states that there is no order book, that any notable historical pattern is purely chance, and that external news does not affect these prices.

## Preconditions
UTC timestamps, broker and symbol identity, a known synthetic-index family, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.1.0","inputs":{"description":"closed_candles (UTC), timeframe, nominal_volatility (50% to 100%), tick_interval_seconds (2 or 1)"}}`

## JSON output
`{"cycle_id":"string","skill":"constant-volatility-validation","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Compare realised annualised volatility with the nominal value over rolling windows; test autocorrelation of returns and of absolute returns (Ljung-Box), the variance ratio at several horizons and the excess kurtosis. If returns look independent with stable variance, directional rules have no structural basis and the answer is WAIT; the useful output is the volatility itself, for sizing stops and position size.

## Evidence so far
Volatility 75 produced a spread of 0.19 times the typical five-minute move and a chronological test period below 1 for the moving-average baseline, consistent with no exploitable structure.

## Limits
Sample noise: with a few thousand bars small autocorrelations are not distinguishable from zero; report confidence intervals. The nominal-volatility convention of the provider must be confirmed before comparing. This specification has no calibrated probability or verified economic edge. Scores are qualitative.

## Positive example
A fresh, complete sample of a known family yields a traceable report with the measured statistic, its confidence interval, the sample size and a UTC cycle ID; even a directional report cannot bypass the risk engine.

## Negative example
Unknown family, too few observations, a pattern that does not beat the random-entry null, or a stale quote yields WAIT and a reason.

## Abstention
WAIT on missing data, unknown family, insufficient sample size (fewer than 30 events), significance not reached after correction for the number of tests, or conflicting evidence.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. Implementation pending validation.
