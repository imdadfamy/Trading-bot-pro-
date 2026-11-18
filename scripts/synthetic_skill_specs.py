"""Research skills specific to synthetic indices (Deriv Volatility, Boom/Crash, Drift Switching, DEX, Jump, Step).

Grounded in Deriv's public description of these markets (https://deriv.com/markets/derived-indices/synthetic-indices,
read on 18 November 2026) and in measurements made on the project's demo account (see docs/INDICES_SYNTHETIQUES.md).
Original text, no third-party code.
"""

SOURCES = (
    "Deriv, 'Synthetic indices' (read 18 Nov 2026): markets simulated and open 24/7 (Sunday 00:00 to Saturday 24:00 GMT); "
    "Volatility indices have constant volatility from 50% to 100% with a tick every 2 s (or every 1 s); Crash/Boom indices "
    "have a crash or boom every 500 ticks on average (300, 500, 600, 900 and 1000 exist); Drift Switching indices alternate "
    "between up, down and sideways trends with changes every 10, 20 or 30 minutes on average; DEX indices show marked spikes "
    "and drops every 10, 15 or 25 minutes on average; Jump indices jump every 20 minutes on average, up or down with equal "
    "chance, at about 30 times normal volatility; Step indices move by a fixed 0.3, 0.4 or 0.5 at each tick. Deriv also states "
    "that there is no order book, that any notable historical pattern is purely chance, and that external news does not "
    "affect these prices."
)

SKILLS = [
    {
        "id": "synthetic-index-mechanics",
        "name": "Synthetic Index Mechanics",
        "owner": "quant",
        "objective": "Identify the family of a synthetic index from its symbol and state what is random BY CONSTRUCTION, so that only meaningful questions are asked of the data.",
        "inputs": "symbol, broker, closed_candles (UTC, bid/ask), contract_metadata (tick size, volume limits)",
        "method": "Map the symbol to a family (Volatility, Boom, Crash, Drift Switching, DEX, Jump, Step, Range Break, other). List the family's documented invariants and verify each on the sample: Step moves are exactly +-step; Volatility returns have stable standard deviation; Boom has only upward spikes and Crash only downward ones; Jump spikes are symmetric. Report which hypotheses remain admissible (for example a drift between spikes) and which are excluded by construction (news impact, order-flow patterns). State the sample size behind every verdict.",
        "limits": "Mechanics come from the provider's public description and can change; a measured invariant on a short sample is evidence, not proof. Unknown families must not be guessed: answer WAIT.",
        "evidence": "On 17 days of M5 bars of the demo account: Boom 500 showed 757 upward moves above 0.1% and none downward; Crash 500 the reverse; Volatility 75 was symmetric (1,635 up, 1,657 down).",
    },
    {
        "id": "spike-process-analysis",
        "name": "Spike Process Analysis",
        "owner": "quant",
        "objective": "Characterise the spike process of Boom, Crash, DEX and Jump indices: rate, direction, size and whether the waiting time between spikes is memoryless.",
        "inputs": "closed_candles (UTC, OHLC), timeframe, spike_threshold (default 5 times the median absolute bar return of the previous 100 bars)",
        "method": "Flag spike bars with the fixed rule; estimate the rate per bar with a Wilson 95% interval; build the distribution of bars since the previous spike and compare its hazard (probability of a spike given k calm bars) with a constant hazard; test directional asymmetry and the size distribution. A constant hazard means waiting for a spike to be 'due' carries no information.",
        "limits": "Bars aggregate ticks: several spikes in one bar are counted once and a spike straddling two bars is split. Needs at least 30 spikes, otherwise abstain. The rate is a historical description, not a forecast.",
        "evidence": "Deriv documents a spike every 500 ticks on average for Boom 500 and Crash 500; per five-minute bar this appears as roughly one bar in seven carrying a large one-sided move in the measured sample.",
    },
    {
        "id": "drift-regime-detection",
        "name": "Drift Regime Detection",
        "owner": "quant",
        "objective": "Detect the sign of the drift in Drift Switching indices and between spikes in Boom/Crash, and measure how late the detection is compared with the regime length.",
        "inputs": "closed_candles (UTC), timeframe, nominal_regime_minutes (10, 20 or 30 for Drift Switching), cusum_parameters",
        "method": "Estimate the drift with a rolling mean of log returns and a sequential change detector (CUSUM or Page-Hinkley) with fixed parameters chosen before looking at results. Report the current regime, its age, a t-statistic, and the detection delay measured on past regimes. Compare any rule using this signal with random entries (see null-hypothesis-testing).",
        "limits": "Regimes last minutes on average: a detector that needs several bars to be confident may spend most of a regime waiting. Abstain when the t-statistic is below the fixed threshold or the regime is younger than the median detection delay.",
        "evidence": "Not yet measured on Drift Switching data of the demo account; the specification exists so that the first measurement is made with fixed parameters and a null comparison.",
    },
    {
        "id": "constant-volatility-validation",
        "name": "Constant Volatility Validation",
        "owner": "quant",
        "objective": "Check that a Volatility index behaves as announced (constant nominal volatility, independent returns) before any claim of predictability is entertained.",
        "inputs": "closed_candles (UTC), timeframe, nominal_volatility (50% to 100%), tick_interval_seconds (2 or 1)",
        "method": "Compare realised annualised volatility with the nominal value over rolling windows; test autocorrelation of returns and of absolute returns (Ljung-Box), the variance ratio at several horizons and the excess kurtosis. If returns look independent with stable variance, directional rules have no structural basis and the answer is WAIT; the useful output is the volatility itself, for sizing stops and position size.",
        "limits": "Sample noise: with a few thousand bars small autocorrelations are not distinguishable from zero; report confidence intervals. The nominal-volatility convention of the provider must be confirmed before comparing.",
        "evidence": "Volatility 75 produced a spread of 0.19 times the typical five-minute move and a chronological test period below 1 for the moving-average baseline, consistent with no exploitable structure.",
    },
    {
        "id": "synthetic-cost-and-contract-check",
        "name": "Synthetic Cost And Contract Check",
        "owner": "risk",
        "objective": "Turn a candidate trade on a synthetic index into its true cost and feasibility on the broker's contract, before it reaches the risk engine.",
        "inputs": "symbol, bid, ask, bar_range, contract_metadata (volume min/max/step, stops level, filling modes, margin, swaps), planned_holding_time",
        "method": "Compute the spread as a share of the typical bar move and of the planned stop; verify the minimum stop distance measured from the CLOSING price (bid for a long, ask for a short) as stops level plus spread; verify volume limits and step, the broker's allowed fill mode, margin required and overnight swap if the position can cross the rollover. Express the round-trip cost in R. Veto when the cost exceeds a configured share of the expected reward.",
        "limits": "Swaps, commissions and slippage are not exposed by the terminal's Python API and must be read from the contract specification or the provider. Costs are those observed at one moment.",
        "evidence": "Verified with order_check on the demo account: the broker rejected a stop of 0.40 on gold and accepted 0.60, matching stops level (0.20) plus the spread of the moment (0.29).",
    },
    {
        "id": "null-hypothesis-testing",
        "name": "Null Hypothesis Testing",
        "owner": "quant",
        "objective": "Decide whether a rule beats chance, because on synthetic indices any historical pattern may be coincidence.",
        "inputs": "rule_signals, closed_candles (bid/ask), cost_model, trade_ledger, chronological_split",
        "method": "Replay random entries with the same trade frequency and side mix under the same cost model, many times; report the rule's expectancy against that null distribution as a p-value; require the chronological test period to be positive; divide the significance level by the number of rules tried (Bonferroni); require at least 30 trades; fix all parameters before looking at results and never retune on the test period. A passing rule is a hypothesis to confirm on new data, never a validated edge.",
        "limits": "The null models entry timing only; it does not capture every form of dependence. Repeated testing inflates false positives even with a correction. Results describe the sample period.",
        "evidence": "Implemented by the evaluate-rules command; a planted edge is detected and pure noise is not, in the project's tests.",
    },
    {
        "id": "synthetic-risk-sizing",
        "name": "Synthetic Risk Sizing",
        "owner": "risk",
        "objective": "Size and veto trades on synthetic indices given their unusual contract limits and spike risk.",
        "inputs": "equity, risk_fraction, stop_distance, contract_metadata (point value, volume min/max/step, stops level, margin), spike_size_estimate",
        "method": "Compute the volume that risks the configured fraction, round DOWN to the step, and veto if the minimum volume already exceeds the risk budget (for example 0.2 lot on Boom and Crash). Add the typical spike size to the stop distance when estimating the worst loss, because a spike can gap through a stop. Check margin and the maximum volume; refuse positions that could be held across a rollover without accounting for the swap.",
        "limits": "Stops on these markets are not protected against spikes; actual loss can exceed the planned risk. Point value must come from the broker's tick value and tick size, not from assumptions.",
        "evidence": "On the demo account Boom 500 and Crash 500 require a minimum of 0.2 lot and stops of about 1,000 points or more, so the minimum risk per trade can exceed a small risk budget.",
    },
]
