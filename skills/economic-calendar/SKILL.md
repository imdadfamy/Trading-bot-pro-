# Economic Calendar

Version: 0.2.0
Owner: news agent
Scope: XAUUSD
Status: research specification, enriched 19 Nov 2026; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
Decide when scheduled announcements make new entries on gold unwise, without guessing the direction of the reaction.

## Sources
U.S. Bureau of Labor Statistics release schedule (Employment Situation and Consumer Price Index, published at 08:30 Eastern; schedule page for November 2026 cited in the operator's research); Federal Reserve FOMC calendar. A study of gold futures cited in the operator's research associates some announcements with higher volatility and transaction costs (not re-read by the project). Project data: config/us_events.json, 90 announcements to January 2028.

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{"cycle_id":"string","skill_version":"0.2.0","inputs":{"description":"scheduled_us_announcements (kind, time), observed_at, features.spread and atr"}}`

## JSON output
`{"cycle_id":"string","skill":"economic-calendar","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}`

## Method
Look at the scheduled announcements within the next 24 hours. Inside the window around a release (15 minutes before and after, longer if spread and volatility stay high) new entries are suspended; the project's code already enforces the window for gold. Outside the window treat the next release as a risk reason to reduce, not as a signal. Direction would need the actual figure against the consensus and the previous value; no consensus data is available here, so no directional use is possible.

## Evidence
The project's calendar covers NFP, CPI, PPI and FOMC with the window of the specification. No test of the direction of reactions has been run and none is supported: a mechanical 'positive number means gold falls' rule is explicitly rejected by the specification.

## Decision rules
Return WAIT inside a window. Outside it, mention an upcoming release within 2 hours as a reason for caution and keep your vote to the price evidence. Never infer a direction from the event kind alone.

## Limits
Unscheduled news is not in the calendar. Times are UTC; daylight saving changes the UTC hour of the 08:30 Eastern release.

## Positive example
'CPI in 40 minutes: caution; price evidence neutral: WAIT.'

## Negative example
'NFP is today so SELL gold' is invalid.

## Abstention
WAIT inside a window, or when the calendar is missing or expired.

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
