# Institutional Flow

Version: 0.2.0
Owner: news agent
Scope: XAUUSD
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Use trader positioning reports as slow context while respecting their publication date.

## Sources
CFTC Commitments of Traders reports and 'About the COT Reports' (cited in the operator's research): weekly report, data as of Tuesday and published later in the week (normally Friday afternoon Eastern). Never attribute the information before its publication time.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"cot context fields when supplied (as-of date, publication date, net positions), otherwise none"}}`

## JSON output
`{"cycle_id":"string","skill":"institutional-flow","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Treat positioning as a weekly background. A test or a decision may only use a report whose publication time is before the decision time; the as-of date (Tuesday) is earlier than the publication date and must not be used as the date of knowledge.

## Evidence
The project does not yet ingest COT data: no such field is supplied. No test has been run.

## Decision rules
Abstain if no field is supplied or if its publication time is after the decision time. Positioning extremes are context for caution, not a trade trigger.

## Limits
Weekly and delayed; reflects futures markets, not the broker's CFD.

## Positive example
'No positioning data supplied: nothing to add.'

## Negative example
Using Tuesday's positions on Tuesday morning is look-ahead and invalid.

## Abstention
WAIT on this question when data are absent or not yet published.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
