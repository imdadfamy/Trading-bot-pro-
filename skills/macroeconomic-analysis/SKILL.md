# Macroeconomic Analysis

Version: 0.2.0
Owner: news agent
Scope: XAUUSD
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Use real interest rates and the dollar as slow context for gold, never as a minute-level entry signal.

## Sources
Chicago Fed Letter No. 464, 'What Drives Gold Prices?' (2021; cited in the operator's research, not re-read by the project): relationship between gold and real interest rates. FRED daily series that fit: DFII10 (10-year inflation-indexed Treasury yield) and DTWEXBGS (broad U.S. dollar index).

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"macro context fields when supplied (real yield, dollar index and their changes), otherwise none"}}`

## JSON output
`{"cycle_id":"string","skill":"macroeconomic-analysis","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Use the sign of the multi-day change of the 10-year real yield and of the dollar as background only: falling real yields and a weaker dollar have historically coincided with higher gold, with regime changes. These series are daily and published with delay, so use only values available at the decision time.

## Evidence
The project does not yet ingest these series: no macro field is supplied to the agents. No test of their usefulness at the project's horizon has been run.

## Decision rules
If no macro field is supplied, say so and abstain on the macro question. Never invent a yield or an index level. Macro context may justify caution or a tie-break, not an entry by itself.

## Limits
Correlation is not causation and changes with regimes; daily data cannot time a five-minute entry.

## Positive example
'No macro data supplied: macro question left open; vote from price evidence.'

## Negative example
Quoting a yield level that was not in the input is invalid.

## Abstention
WAIT on the macro question when fields are absent, stale or unavailable at decision time.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
