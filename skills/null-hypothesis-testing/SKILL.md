# Null Hypothesis Testing

Version: 0.2.0
Owner: quant agent
Scope: synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Keep every claim of an edge honest by testing it against random entries and counting every variant tried.

## Sources
Project rule bench (backend/trading_pro/synthetic_rules.py) and the multiple-testing practice of the sources read: MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a holdout evaluated several times. Treat as a hypothesis to test, never as proof. Deriv states that notable historical patterns on these indices can be chance.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"trade ledger of a rule, number of variants tried, chronological periods"}}`

## JSON output
`{"cycle_id":"string","skill":"null-hypothesis-testing","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Compare a rule's expectancy in R with 300 or more random-entry runs that have the same trade frequency and side mix under the same costs. Divide the significance level by the number of rules tested (Bonferroni; Holm is stricter in sequence). Require at least 30 trades, a positive expectancy and a profitable chronological test period. Count every parameter combination tried, not only the one reported.

## Evidence
Project results so far: the 5/20 moving-average baseline on XAUUSD M5 had profit factor 0.73; Boom 0.96, Crash 1.02 and Volatility 75 1.07 with spike-gap stops, none significant against chance. The Volatility 10 moving-average and RSI reading tested 19 Nov 2026: p = 0.72, 0.33, 0.74, 0.22 against random entries. The outside study needed t of about 4 or more after 1,578 variants.

## Decision rules
Never call a result significant on fewer than 30 trades, on the training period alone, or without stating how many variants were tried. A profit factor above 1 on a small sample is a coincidence until a new period confirms it.

## Limits
Random entries share the rule's cost model, so a rule can look good only if its timing beats chance; slow regime effects are not captured by a short sample.

## Positive example
'18 trades, expectancy +0.3 R, p = 0.2, not significant, sample too small' is the expected phrasing.

## Negative example
'Profit factor 1.4 so the strategy works' is invalid.

## Abstention
WAIT whenever evidence rests on fewer than 30 trades or an uncorrected test.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
