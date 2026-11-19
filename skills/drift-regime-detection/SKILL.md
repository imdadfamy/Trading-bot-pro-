# Drift Regime Detection

Version: 0.2.0
Owner: quant agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Detect whether a Drift Switch (or any drifting synthetic) index is in an up, down or sideways drift, and whether staying with the drift pays after costs.

## Sources
Deriv, 'Synthetic indices' (read 18 Nov 2026): Drift Switching indices alternate between up, down and sideways trends, changing every 10, 20 or 30 minutes on average. Symbols present on the project's demo account: Drift Switch Index 10, 20 and 30. MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a holdout evaluated several times. Treat as a hypothesis to test, never as proof. Independent research repository Orphy123/deriv-research (README read 19 Nov 2026; MIT licence, small, self-published): a pre-registered Post-Spike Drift Capture hypothesis was falsified on Boom 1000 and Crash 1000 and a drift-regime filter was killed at its autocorrelation gate. Its conclusion: no exploitable structure after costs on those two contracts.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"features.drift (60 bars) and features.drift_short (20 bars): mean return per bar and t statistic; SMA 20/50 relation; closed candles. Drift Switch indices are read on M1 bars"}}`

## JSON output
`{"cycle_id":"string","skill":"drift-regime-detection","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Estimate the drift as the mean bar return over the last N bars with its t statistic (N about twice the average regime length in bars). A regime is 'up' or 'down' when |t| is at least 2 and the SMA 20 agrees with the sign; otherwise sideways. Regime changes are random with a documented average length, so the expected remaining duration is that average, not a schedule.

## Evidence
The only synthetic family for which an outside party reports a surviving trend-following edge after multiple-testing correction is Drift Switch 10/20/30, from a seller with a commercial interest and no forward test (see Sources). The same author found nothing on Volatility, Boom, Crash, Step, Range Break, DEX or Jump. The independent repository tested a drift filter on Boom 1000 and Crash 1000 and abandoned it. The project has not yet measured Drift Switch itself.

## Decision rules
Vote with the detected drift only when |t| is at least 2 and the SMA 20 agrees; otherwise WAIT. A reversal vote is not supported by any evidence. Mention in the rationale that the Drift Switch edge is an unverified outside claim.

## Limits
The drift t statistic lags a regime change by design; with average regimes of 10 minutes on M1 bars the signal is mostly late. Costs about twice smaller than the claimed edge leave little margin.

## Positive example
Drift Switch Index 20, 40 M1 bars, mean return clearly positive with t = 3.1 and SMA 20 above SMA 50: BUY, score null, rationale states the sample length and that the edge is unverified.

## Negative example
t = 0.8: sideways, WAIT. Applying the rule to Boom or Crash is invalid.

## Abstention
WAIT on missing features, |t| below 2, disagreement with the SMA, or an instrument without a drift mechanism.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
