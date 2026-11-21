"""Enriched research skills (version 0.2.0 and new ones), written from sources read on 19 November 2026 and from
measurements made on the project's demo account. Run: python scripts/enriched_skill_specs.py

Every statement is either (a) attributed to a source the project read, (b) measured on our own data with the
numbers given, or (c) marked as unverified. No skill claims a validated edge. Original text, no third-party code.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills"
VERSION = "0.2.0"
TEMPLATE = """# {name}

Version: {version}
Owner: {owner} agent
Scope: {scope_text}
Status: research specification, enriched {date}; no validated trading edge
Licence: original project documentation, no third-party code included.

## Objective
{objective}

## Sources
{sources}

## Preconditions
UTC timestamps, broker and symbol identity, validated finite numeric values; abort on missing or contradictory inputs. Never send broker orders.

## JSON input
`{{"cycle_id":"string","skill_version":"{version}","inputs":{{"description":"{inputs}"}}}}`

## JSON output
`{{"cycle_id":"string","skill":"{id}","action":"BUY|SELL|WAIT","rationale":"string","evidence":["measurement id"],"score":null,"invalidations":["condition"]}}`

## Method
{method}

## Evidence
{evidence}

## Decision rules
{rules}

## Limits
{limits}

## Positive example
{positive}

## Negative example
{negative}

## Abstention
{abstention}

## Tests and metrics
Fixture: missing input => WAIT; planted structure => detected; pure noise => not detected. Measure coverage, abstention, p-values against the random-entry null and net outcome after real costs on held-out samples. The experiment ledger measures this skill by comparing decisions made with it and without it.
"""

DERIV_ACADEMY = ("Deriv Traders Academy guides read 19 Nov 2026: 'Why did my stop-loss close at a different price on Boom and Crash "
                 "Indices?' (stop is a trigger, not a guaranteed price; each tick is independent and a spike is not more likely because "
                 "none happened recently), 'Crash & Boom 150' and 'Volatility Indices explained' (1s and 2s versions of the same volatility "
                 "level are generated independently and do not move in sync; historical patterns do not predict the next move).")
ORPHY = ("Independent research repository Orphy123/deriv-research (README read 19 Nov 2026; MIT licence, small, self-published): "
         "a pre-registered Post-Spike Drift Capture hypothesis was falsified on Boom 1000 and Crash 1000 and a drift-regime filter was "
         "killed at its autocorrelation gate. Its conclusion: no exploitable structure after costs on those two contracts.")
AUREUS = ("MQL5 blog post 'Strategy Variants on Synthetic Indices' (read 19 Nov 2026; written by the seller of a commercial EA, so a "
          "conflict of interest): 1,578 variants over 53 symbols, Holm correction (needs t of about 4 or more), walk-forward with costs "
          "from published specifications. Volatility, Boom, Crash, Step, Range Break, DEX and Jump: no survivor. Only Drift Switch 10/20/30 "
          "passed, with about 8 to 10 basis points net per trade, roughly twice the round-trip cost, no live or demo forward test, and a "
          "holdout evaluated several times. Treat as a hypothesis to test, never as proof.")

SKILLS = [
    {
        "id": "spike-process-analysis", "name": "Spike Process Analysis", "owner": "quant", "scope": "synthetic",
        "agents": ["quant", "graph"], "families": ["boom", "crash", "jump", "dex"],
        "objective": "Characterise the spike process of Boom, Crash, DEX and Jump indices (rate, direction, size) and decide whether the time since the last spike carries any information.",
        "sources": DERIV_ACADEMY + " " + ORPHY + " " + AUREUS,
        "inputs": "features.spikes (count, mean interval in bars, bars since last spike, median and p90 spike move), closed candles, family",
        "method": "Spikes are bars whose close-to-close move is at least 5 times the median absolute move of the previous 100 bars, in the direction of the family (Boom up, Crash down). Use features.spikes: the mean interval is the average spacing, bars_since_last_spike is only a description. Waiting time between spikes is geometric if the process is memoryless: its coefficient of variation is close to the square root of (1 - p).",
        "evidence": "Measured 19 Nov 2026 on 50,000 M1 bars of the demo account. Boom 1000: 2,301 spikes flagged, mean 21.7 bars apart, coefficient of variation 0.996 (a memoryless process gives 0.977), Kolmogorov-Smirnov p = 0.25, spike hazard after a short wait 0.0469 versus 0.0454 after a long wait. Crash 1000: 2,398 spikes, mean 20.8 bars, variation 0.950 (0.976), p = 0.67, hazard 0.0470 versus 0.0493. Median spike about 0.107% of price, 90th percentile about 0.21%, roughly nine times the average one-minute bar range. Conclusion: consistent with a memoryless process; a spike is never 'due'.",
        "rules": "Never argue that a spike is overdue or imminent from elapsed time. Direction between spikes: Boom drifts down and Crash drifts up in small steps, so holding against the spike direction bleeds until the spike, and holding with it risks nothing special except the cost. Vote BUY or SELL only when the measured features support a specific, stated hypothesis and costs (spread as a share of typical bar range) are small; otherwise WAIT. Report the spike rate, the interval statistics and the sample size in the rationale.",
        "limits": "Bars aggregate ticks: several spikes in one bar count once and a spike across two bars is split. At least 30 spikes are needed. A rate describes the past and is not a forecast. Only Boom and Crash 1000 were measured here; other contracts need their own measurement.",
        "positive": "Boom 1000 with 40 flagged spikes in the window, features complete, spread small relative to the bar range: the rationale cites the interval statistics, states that elapsed time is uninformative, and still returns WAIT because no edge is shown.",
        "negative": "'No spike for 50 bars, so a spike is due, BUY Boom' is invalid: the hazard is flat. Fewer than 30 spikes in the sample also gives WAIT.",
        "abstention": "WAIT on missing features, unknown family, fewer than 30 spikes, or any claim that rests on elapsed time since the last spike.",
    },
    {
        "id": "boom-crash-stop-gap-risk", "name": "Boom and Crash Stop Gap Risk", "owner": "risk", "scope": "synthetic",
        "agents": ["quant", "graph"], "families": ["boom", "crash"],
        "objective": "Measure how far a stop can be jumped by a spike so that risk is judged on the possible loss, not on the requested stop distance.",
        "sources": DERIV_ACADEMY + " " + AUREUS,
        "inputs": "features.spikes (p90 spike move), features.atr_14, spread, stop distance, side, family",
        "method": "A stop is a trigger, not a guaranteed price: after a spike the order fills at the first available price. The adverse side is a sell on Boom (up spikes) and a buy on Crash (down spikes). Compare the planned stop distance with the median and 90th-percentile spike moves; an effective risk multiple is max(stop, spike move) / stop on the adverse side. The backtest cost model fills stops at the adverse extreme of a spike bar ('spike_gap').",
        "evidence": "Deriv's own worked example: sell Boom at 10,000, stop 10,010, fill 10,025, planned risk $5 and realised loss $12.50 (illustrative, not execution data). AureusAI measured stops hit by spikes filling at the post-spike quote in 13 of 13 cases, mean overshoot 5.0 basis points. Our M1 measurement: median spike 0.107%, p90 0.21% of price, about nine times a typical bar range, so any stop tighter than about nine bar ranges is likely to be jumped on the adverse side.",
        "rules": "On the adverse side with a stop tighter than the p90 spike, the real risk is about p90 spike / stop times the planned risk: say so and vote WAIT unless the position size is cut accordingly. On the favourable side a spike is a gain beyond the target, not a risk. Never recommend widening a stop to 'survive' without reducing size.",
        "limits": "The overshoot depends on the broker's tick feed; our own order history holds a single trade. Spike sizes were measured on M1 bars of one month for Boom 1000 and Crash 1000.",
        "positive": "Sell Boom 1000 with a stop of 2 bar ranges: the rationale notes that the p90 spike is about nine bar ranges, estimates the effective risk at four to five times the plan, and returns WAIT.",
        "negative": "'The stop limits my loss to X' on Boom or Crash is invalid without the gap statement.",
        "abstention": "WAIT when spike statistics are missing or the stop is below the p90 spike on the adverse side.",
    },
    {
        "id": "volatility-10-ma-rsi-hypothesis", "name": "Volatility 10 Moving Average and RSI Hypothesis", "owner": "quant", "scope": "synthetic",
        "agents": ["quant", "graph"], "families": ["volatility"],
        "objective": "Evaluate the widely circulated swing method for Volatility 10 (20/50 moving averages with RSI on H1 or H4) as a hypothesis, using code-computed features.",
        "sources": "Vince Stanzione, 'How to Trade Synthetic Indices' (PDF published on docs.deriv.com, 2025; read 19 Nov 2026): H1 or H4 chart; SMA 50 for the trend and SMA 20 for the short-term direction; RSI 14; buy when SMA 20 crosses above SMA 50, RSI between 50 and 70, and price pulls back to the SMA 20 without breaking it; sell the mirror with RSI between 30 and 50; exit near recent swing points (about 1 to 2% moves). The guide gives no backtest of this method and its text does not warn that the pattern may be chance. The stock-indices ebook of the same author discloses an affiliate relationship with Deriv; none was found in the text of this PDF. " + DERIV_ACADEMY,
        "inputs": "features.setup_ma_rsi (sma20, sma50, bars since cross, rsi14, pullback flag), timeframe, symbol",
        "method": "Check the five conditions in features.setup_ma_rsi. Report the setup only when all hold on closed bars. The two tick speeds, Volatility 10 and Volatility 10 (1s), are different independent series: never mix their statistics.",
        "evidence": "Our test of one pre-registered reading of the rule (cross within 30 bars, RSI 50-70 or 30-50, pullback within 0.2 ATR of the SMA 20, one entry per cross, stop 2 median bar ranges, target 2R, bid-based bars, 5,000 H1 bars from March to November 2026): Volatility 10 (2s) H1: 81 trades, profit factor 0.84, expectancy -0.11 R, random-entry p = 0.72, test period negative. Volatility 10 (1s) H1: 74 trades, PF 1.14, +0.09 R, p = 0.33, validation and test periods both -0.25 R. H4: 23 and 21 trades, too few; p = 0.74 and 0.22. None beats random entries. The positive training periods reverted out of sample.",
        "rules": "The setup is a hypothesis with no demonstrated edge here. You may vote BUY or SELL when every condition holds (the experiment measures it); give score null and say that the measured expectancy of this rule is about zero. Otherwise WAIT. Do not combine it with spike arguments or news.",
        "limits": "One reading of an ambiguous method on one instrument family; other readings would multiply the tests and need correction. Costs are bar spreads, no commission or slippage measured. Swing exits by 'recent swing' were replaced with a fixed R target.",
        "positive": "H4 Volatility 10 (2s): SMA 20 crossed above SMA 50 eight bars ago, RSI 58, last bar touched the SMA 20 and closed above it: BUY with a short rationale and score null.",
        "negative": "RSI 74, or no recent cross, or the pullback closed below the SMA 20: WAIT. Quoting the guide as proof of profitability is invalid.",
        "abstention": "WAIT when any condition fails, when features are missing, or when bars of the two tick speeds are mixed.",
    },
    {
        "id": "drift-regime-detection", "name": "Drift Regime Detection", "owner": "quant", "scope": "synthetic",
        "agents": ["quant", "graph"], "families": ["drift"],
        "objective": "Detect whether a Drift Switch (or any drifting synthetic) index is in an up, down or sideways drift, and whether staying with the drift pays after costs.",
        "sources": "Deriv, 'Synthetic indices' (read 18 Nov 2026): Drift Switching indices alternate between up, down and sideways trends, changing every 10, 20 or 30 minutes on average. Symbols present on the project's demo account: Drift Switch Index 10, 20 and 30. " + AUREUS + " " + ORPHY,
        "inputs": "features.drift (60 bars) and features.drift_short (20 bars): mean return per bar and t statistic; SMA 20/50 relation; closed candles. Drift Switch indices are read on M1 bars",
        "method": "Estimate the drift as the mean bar return over the last N bars with its t statistic (N about twice the average regime length in bars). A regime is 'up' or 'down' when |t| is at least 2 and the SMA 20 agrees with the sign; otherwise sideways. Regime changes are random with a documented average length, so the expected remaining duration is that average, not a schedule.",
        "evidence": "The only synthetic family for which an outside party reports a surviving trend-following edge after multiple-testing correction is Drift Switch 10/20/30, from a seller with a commercial interest and no forward test (see Sources). The same author found nothing on Volatility, Boom, Crash, Step, Range Break, DEX or Jump. The independent repository tested a drift filter on Boom 1000 and Crash 1000 and abandoned it. The project has not yet measured Drift Switch itself.",
        "rules": "Vote with the detected drift only when |t| is at least 2 and the SMA 20 agrees; otherwise WAIT. A reversal vote is not supported by any evidence. Mention in the rationale that the Drift Switch edge is an unverified outside claim.",
        "limits": "The drift t statistic lags a regime change by design; with average regimes of 10 minutes on M1 bars the signal is mostly late. Costs about twice smaller than the claimed edge leave little margin.",
        "positive": "Drift Switch Index 20, 40 M1 bars, mean return clearly positive with t = 3.1 and SMA 20 above SMA 50: BUY, score null, rationale states the sample length and that the edge is unverified.",
        "negative": "t = 0.8: sideways, WAIT. Applying the rule to Boom or Crash is invalid.",
        "abstention": "WAIT on missing features, |t| below 2, disagreement with the SMA, or an instrument without a drift mechanism.",
    },
    {
        "id": "synthetic-cost-and-contract-check", "name": "Synthetic Cost and Contract Check", "owner": "risk", "scope": "synthetic",
        "agents": ["quant", "graph"],
        "objective": "Check that costs (spread, slippage, commission) are small relative to the move the idea needs, using the instrument's measured contract data.",
        "sources": "MetaTrader 5 contract data and bar spreads read from the project's Deriv demo account (read-only), 19 Nov 2026. " + AUREUS,
        "inputs": "features.spread, features.spread_to_atr, stop distance, target distance, minimum lot, contract size",
        "method": "Compute the round-trip cost as one spread plus assumed slippage and commission. Compare it with the stop distance (cost in R = cost / stop) and with the target. An idea whose cost exceeds about 10% of its stop (0.1 R) loses a tenth of every trade before it starts. Bars are bid-built: a buy pays the full spread on entry.",
        "evidence": "Measured median bar spread: Boom 1000 0.152 on a price near 14,940 (about 9% of the average M1 bar range 1.73); Crash 1000 0.060 on 5,765 (about 9% of an average range 0.70); Volatility 10 (2s) 0.162 and Volatility 10 (1s) 0.33 on H4 bars with prices near 6,000 (about 2% of a median H1 bar range of 7.8 and 15.4 respectively). One real demo order on Volatility 75 cost a spread of 13.7 on a 38,900 price. Commissions: none charged on the one measured order.",
        "rules": "State the cost in R in the rationale. The execution layer widens every stop to at least ten spreads, so the cost stays at or below 0.1 R by construction; vote WAIT only when the idea itself needs a tighter stop than that (for example an M1 scalp) or when the live spread is far above the bar spread. Never ignore the spread because bars look profitable on closes alone.",
        "limits": "Spread is a bar statistic, not tick-by-tick; slippage and commission were measured on a single order. Contract values can change.",
        "positive": "Volatility 10 H1, spread 2% of the stop: cost 0.02 R, acceptable; says so and moves on to the directional question.",
        "negative": "An M1 idea on Boom 1000 with a stop of one bar range: spread is 9% of the stop and a spike can jump it, so WAIT.",
        "abstention": "WAIT when spread or contract data are missing or when cost exceeds 10% of the stop.",
    },
    {
        "id": "null-hypothesis-testing", "name": "Null Hypothesis Testing", "owner": "quant", "scope": "synthetic",
        "agents": ["quant"],
        "objective": "Keep every claim of an edge honest by testing it against random entries and counting every variant tried.",
        "sources": "Project rule bench (backend/trading_pro/synthetic_rules.py) and the multiple-testing practice of the sources read: " + AUREUS + " Deriv states that notable historical patterns on these indices can be chance.",
        "inputs": "trade ledger of a rule, number of variants tried, chronological periods",
        "method": "Compare a rule's expectancy in R with 300 or more random-entry runs that have the same trade frequency and side mix under the same costs. Divide the significance level by the number of rules tested (Bonferroni; Holm is stricter in sequence). Require at least 30 trades, a positive expectancy and a profitable chronological test period. Count every parameter combination tried, not only the one reported.",
        "evidence": "Project results so far: the 5/20 moving-average baseline on XAUUSD M5 had profit factor 0.73; Boom 0.96, Crash 1.02 and Volatility 75 1.07 with spike-gap stops, none significant against chance. The Volatility 10 moving-average and RSI reading tested 19 Nov 2026: p = 0.72, 0.33, 0.74, 0.22 against random entries. The outside study needed t of about 4 or more after 1,578 variants.",
        "rules": "Never call a result significant on fewer than 30 trades, on the training period alone, or without stating how many variants were tried. A profit factor above 1 on a small sample is a coincidence until a new period confirms it.",
        "limits": "Random entries share the rule's cost model, so a rule can look good only if its timing beats chance; slow regime effects are not captured by a short sample.",
        "positive": "'18 trades, expectancy +0.3 R, p = 0.2, not significant, sample too small' is the expected phrasing.",
        "negative": "'Profit factor 1.4 so the strategy works' is invalid.",
        "abstention": "WAIT whenever evidence rests on fewer than 30 trades or an uncorrected test.",
    },
    {
        "id": "synthetic-risk-sizing", "name": "Synthetic Risk Sizing", "owner": "risk", "scope": "synthetic",
        "agents": ["quant"],
        "objective": "Size a position from the money at risk, the real stop distance and the contract rules, and reject what the minimum lot cannot respect.",
        "sources": "Project risk engine and MetaTrader 5 order checks on the demo account, 18 Nov 2026; " + DERIV_ACADEMY,
        "inputs": "equity, risk fraction, stop distance, tick size and value, volume min/step/max, features.spikes",
        "method": "Volume = risk money / (stop distance in ticks times tick value plus costs), rounded down to the step; reject if below the minimum lot. On the adverse side of Boom and Crash replace the stop distance by max(stop, p90 spike) for the risk calculation. Never increase size to recover a loss.",
        "evidence": "Contract data read on the demo account, 21 Nov 2026 (equity about 10,000 USD, leverage 1000). Money moved by one lot for a price move of one unit: every synthetic index below is 1 dollar (contract size 1); XAUUSD is 100 dollars. So a minimum lot of 0.2 on Boom or Crash risks 0.2 dollar per price unit, a hundred times less than 0.2 lot of gold. Minimum lot, minimum stop distance (broker level plus spread), median spread: Volatility 10 0.5 lot, 0.91, 0.19; Boom 500 0.2 lot, 1.70, 0.53; Crash 500 0.2 lot, 1.25, 0.32; Drift Switch 10 0.1 lot, 6.3, 1.29; Drift Switch 20 0.1 lot, 5.3, 0.32; Drift Switch 30 0.1 lot, 15.2, 5.18; XAUUSD 0.01 lot, 0.79, 0.59. At 0.5% risk (about 50 dollars) a Boom 500 stop of 12 price units allows about 4 lots, far above the minimum lot: the minimum lot is never the binding constraint with realistic stops. The broker's order check accepted a minimal buy and sell on all seven instruments. Minimum order margins: Boom 500 about 2.82, Crash 500 1.39, Volatility 10 0.49. The supervised demo order on Volatility 75 used 0.01 lot with a stop of about 364 points and lost 0.72 dollars after about a minute.",
        "rules": "Volume = money at risk divided by (stop distance times money per price unit per lot): the same risk gives a large lot on a synthetic index and a small lot on gold, and that is correct. The stop is the largest of the volatility stop, ten spreads (so the spread costs at most 0.1 R) and, on Boom and Crash, the 90th-percentile spike. On the side a spike runs against, size as if half a stop more could be lost. Do not refuse an instrument for its lot size; refuse only when the cost in R is above 0.1 or the risk engine says so. Never propose more than the engine's per-trade risk and never increase size after a loss.",
        "limits": "Margins and minimum lots are contract values read once and can change; the engine, not the model, decides the final volume.",
        "positive": "'Minimum lot 0.2 risks 3% with the real stop; above the limit, WAIT.'",
        "negative": "Recommending a larger lot after losses is invalid.",
        "abstention": "WAIT when contract data is missing or the minimum lot breaks the risk limit.",
    },
    {
        "id": "synthetic-index-mechanics", "name": "Synthetic Index Mechanics", "owner": "quant", "scope": "synthetic",
        "agents": ["quant", "graph"],
        "objective": "Identify the family of a synthetic index from its symbol and state what is random by construction, so that only meaningful questions are asked of the data.",
        "sources": "Deriv, 'Synthetic indices' (read 18 Nov 2026): simulated, open 24/7, no order book, news does not affect prices, notable historical patterns can be chance. " + DERIV_ACADEMY,
        "inputs": "symbol, closed candles, features",
        "method": "Map the symbol to a family: Volatility (constant volatility; ticks every 2 s or every 1 s), Boom and Crash (spike on average every N ticks, N in the name, up for Boom and down for Crash), Drift Switch, DEX, Jump, Step, Range Break, Flip and Volatility Boom/Crash variants. Volatility 10 and Volatility 10 (1s) are independent series. Only measure what the family can show: news, order flow and sessions have no meaning here.",
        "evidence": "Verified on the project's demo account: Boom shows only upward spikes and Crash only downward ones; Volatility 75 returns are symmetric; Boom and Crash waiting times between spikes behave like a memoryless process (see spike-process-analysis); Volatility 10 and Volatility 10 (1s) both exist and carry different spreads (0.162 and 0.33). Symbols available include Boom/Crash 50 to 1000, Boom/Crash Flip, Volatility Boom/Crash 400/550/750 and Drift Switch Index 10/20/30.",
        "rules": "Do not use news, sessions or macro arguments for these symbols. Name the family and the number in the symbol in the rationale. Unknown family: WAIT.",
        "limits": "Mechanics come from the provider's description and may change; a measured invariant on a short sample is evidence, not proof.",
        "positive": "'Crash 500: downward spikes by construction, drift upward between spikes; no news channel; judging only price features.'",
        "negative": "Quoting a US announcement as a reason to trade Boom is invalid.",
        "abstention": "WAIT on an unknown family or insufficient sample.",
    },
    # ---- core (gold) skills
    {
        "id": "economic-calendar", "name": "Economic Calendar", "owner": "news", "scope": "core",
        "agents": ["news"],
        "objective": "Decide when scheduled announcements make new entries on gold unwise, without guessing the direction of the reaction.",
        "sources": "U.S. Bureau of Labor Statistics release schedule (Employment Situation and Consumer Price Index, published at 08:30 Eastern; schedule page for November 2026 cited in the operator's research); Federal Reserve FOMC calendar. A study of gold futures cited in the operator's research associates some announcements with higher volatility and transaction costs (not re-read by the project). Project data: config/us_events.json, 90 announcements to January 2028.",
        "inputs": "scheduled_us_announcements (kind, time), observed_at, features.spread and atr",
        "method": "Look at the scheduled announcements within the next 24 hours. Inside the window around a release (15 minutes before and after, longer if spread and volatility stay high) new entries are suspended; the project's code already enforces the window for gold. Outside the window treat the next release as a risk reason to reduce, not as a signal. Direction would need the actual figure against the consensus and the previous value; no consensus data is available here, so no directional use is possible.",
        "evidence": "The project's calendar covers NFP, CPI, PPI and FOMC with the window of the specification. No test of the direction of reactions has been run and none is supported: a mechanical 'positive number means gold falls' rule is explicitly rejected by the specification.",
        "rules": "Return WAIT inside a window. Outside it, mention an upcoming release within 2 hours as a reason for caution and keep your vote to the price evidence. Never infer a direction from the event kind alone.",
        "limits": "Unscheduled news is not in the calendar. Times are UTC; daylight saving changes the UTC hour of the 08:30 Eastern release.",
        "positive": "'CPI in 40 minutes: caution; price evidence neutral: WAIT.'",
        "negative": "'NFP is today so SELL gold' is invalid.",
        "abstention": "WAIT inside a window, or when the calendar is missing or expired.",
    },
    {
        "id": "macroeconomic-analysis", "name": "Macroeconomic Analysis", "owner": "news", "scope": "core",
        "agents": ["news"],
        "objective": "Use real interest rates and the dollar as slow context for gold, never as a minute-level entry signal.",
        "sources": "Chicago Fed Letter No. 464, 'What Drives Gold Prices?' (2021; cited in the operator's research, not re-read by the project): relationship between gold and real interest rates. FRED daily series that fit: DFII10 (10-year inflation-indexed Treasury yield) and DTWEXBGS (broad U.S. dollar index).",
        "inputs": "macro context fields when supplied (real yield, dollar index and their changes), otherwise none",
        "method": "Use the sign of the multi-day change of the 10-year real yield and of the dollar as background only: falling real yields and a weaker dollar have historically coincided with higher gold, with regime changes. These series are daily and published with delay, so use only values available at the decision time.",
        "evidence": "The project does not yet ingest these series: no macro field is supplied to the agents. No test of their usefulness at the project's horizon has been run.",
        "rules": "If no macro field is supplied, say so and abstain on the macro question. Never invent a yield or an index level. Macro context may justify caution or a tie-break, not an entry by itself.",
        "limits": "Correlation is not causation and changes with regimes; daily data cannot time a five-minute entry.",
        "positive": "'No macro data supplied: macro question left open; vote from price evidence.'",
        "negative": "Quoting a yield level that was not in the input is invalid.",
        "abstention": "WAIT on the macro question when fields are absent, stale or unavailable at decision time.",
    },
    {
        "id": "institutional-flow", "name": "Institutional Flow", "owner": "news", "scope": "core",
        "agents": ["news"],
        "objective": "Use trader positioning reports as slow context while respecting their publication date.",
        "sources": "CFTC Commitments of Traders reports and 'About the COT Reports' (cited in the operator's research): weekly report, data as of Tuesday and published later in the week (normally Friday afternoon Eastern). Never attribute the information before its publication time.",
        "inputs": "cot context fields when supplied (as-of date, publication date, net positions), otherwise none",
        "method": "Treat positioning as a weekly background. A test or a decision may only use a report whose publication time is before the decision time; the as-of date (Tuesday) is earlier than the publication date and must not be used as the date of knowledge.",
        "evidence": "The project does not yet ingest COT data: no such field is supplied. No test has been run.",
        "rules": "Abstain if no field is supplied or if its publication time is after the decision time. Positioning extremes are context for caution, not a trade trigger.",
        "limits": "Weekly and delayed; reflects futures markets, not the broker's CFD.",
        "positive": "'No positioning data supplied: nothing to add.'",
        "negative": "Using Tuesday's positions on Tuesday morning is look-ahead and invalid.",
        "abstention": "WAIT on this question when data are absent or not yet published.",
    },
]

DATE = "19 Nov 2026"


def main():
    catalog_path = ROOT / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in catalog}
    for spec in SKILLS:
        scope_text = ("synthetic indices (Volatility, Boom/Crash, Drift Switch, DEX, Jump, Step)" if spec["scope"] == "synthetic"
                      else "XAUUSD")
        text = TEMPLATE.format(version=VERSION, date=DATE, scope_text=scope_text, **{k: v for k, v in spec.items() if k not in ("scope", "agents", "families")})
        folder = ROOT / spec["id"]
        folder.mkdir(exist_ok=True)
        (folder / "SKILL.md").write_text(text, encoding="utf-8")
        entry = by_id.get(spec["id"])
        if entry is None:
            entry = {"id": spec["id"], "name": spec["name"], "owner": spec["owner"], "version": VERSION,
                     "state": "research_specification", "scope": spec["scope"]}
            catalog.append(entry)
            by_id[spec["id"]] = entry
        entry["version"] = VERSION
        entry["agents"] = spec["agents"]
        if spec.get("families"):
            entry["families"] = spec["families"]
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(SKILLS)} skills written; catalogue now {len(catalog)} entries")


if __name__ == "__main__":
    main()
