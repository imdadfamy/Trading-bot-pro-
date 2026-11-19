# Volatility 10 Moving Average and RSI Hypothesis

Version: 0.2.0
Owner: quant agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Evaluate the widely circulated swing method for Volatility 10 (20/50 moving averages with RSI on H1 or H4) as a hypothesis, using code-computed features.

## Sources
Vince Stanzione, 'How to Trade Synthetic Indices' (PDF published on docs.deriv.com, 2025; read 19 Nov 2026): H1 or H4 chart; SMA 50 for the trend and SMA 20 for the short-term direction; RSI 14; buy when SMA 20 crosses above SMA 50, RSI between 50 and 70, and price pulls back to the SMA 20 without breaking it; sell the mirror with RSI between 30 and 50; exit near recent swing points (about 1 to 2% moves). The guide gives no backtest of this method and its text does not warn that the pattern may be chance. The stock-indices ebook of the same author discloses an affiliate relationship with Deriv; none was found in the text of this PDF. Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility level are generated independently and do not move in sync; historical patterns do not predict the next move).

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"features.setup_ma_rsi (sma20, sma50, bars since cross, rsi14, pullback flag), timeframe, symbol"}}`

## JSON output
`{"cycle_id":"string","skill":"volatility-10-ma-rsi-hypothesis","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Check the five conditions in features.setup_ma_rsi. Report the setup only when all hold on closed bars. The two tick speeds, Volatility 10 and Volatility 10 (1s), are different independent series: never mix their statistics.

## Evidence
Our test of one pre-registered reading of the rule (cross within 30 bars, RSI 50-70 or 30-50, pullback within 0.2 ATR of the SMA 20, one entry per cross, stop 2 median bar ranges, target 2R, bid-based bars, 5,000 H1 bars from March to November 2026): Volatility 10 (2s) H1: 81 trades, profit factor 0.84, expectancy -0.11 R, random-entry p = 0.72, test period negative. Volatility 10 (1s) H1: 74 trades, PF 1.14, +0.09 R, p = 0.33, validation and test periods both -0.25 R. H4: 23 and 21 trades, too few; p = 0.74 and 0.22. None beats random entries. The positive training periods reverted out of sample.

## Decision rules
The setup is a hypothesis with no demonstrated edge here. You may vote BUY or SELL when every condition holds (the experiment measures it); give score null and say that the measured expectancy of this rule is about zero. Otherwise WAIT. Do not combine it with spike arguments or news.

## Limits
One reading of an ambiguous method on one instrument family; other readings would multiply the tests and need correction. Costs are bar spreads, no commission or slippage measured. Swing exits by 'recent swing' were replaced with a fixed R target.

## Positive example
H4 Volatility 10 (2s): SMA 20 crossed above SMA 50 eight bars ago, RSI 58, last bar touched the SMA 20 and closed above it: BUY with a short rationale and score null.

## Negative example
RSI 74, or no recent cross, or the pullback closed below the SMA 20: WAIT. Quoting the guide as proof of profitability is invalid.

## Abstention
WAIT when any condition fails, when features are missing, or when bars of the two tick speeds are mixed.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
