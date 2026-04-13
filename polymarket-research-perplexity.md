# Polymarket Strategies With Real-World Evidence and Open-Source Building Blocks

## Executive Summary

This report synthesizes documented Polymarket trading approaches that have real-world usage, public code, or third-party analysis, then ranks them by practical potential to grow a very small bankroll (for example 10 units of capital) while still being repeatable rather than pure lottery tickets. The core conclusion is that sustainable edge comes from systematic positive expected value (EV) combined with risk-aware position sizing and execution automation; explosive 100× runs in a month are rare outliers, typically tied to concentrated risk in niche markets like weather or specific event upsets.[^1][^2][^3][^4][^5][^6]

The highest quality edges observed in the wild cluster into four families: single-market arbitrage and market-making, model-based forecasting with fractional Kelly sizing, domain-specific informational edges (especially weather), and structured copy-trading on top-performing wallets. Complex combinatorial and cross-venue arbitrage is real but captures a small slice of total profits relative to its infrastructure cost, and is therefore less attractive for a small, fast-scaling bankroll.[^7][^8][^2][^4][^5][^1]


## Strategy Landscape Overview

Polymarket has evolved into a central limit order book (CLOB) venue with zero trading fees on most markets plus occasional maker rebates, creating attractive microstructure edges for liquidity provision and short-horizon trading. Academic and practitioner analyses of on-chain data show two primary arbitrage modes: intra-market rebalancing within a single condition and inter-market combinatorial arbitrage across related markets. In parallel, a wave of open-source bots and agent frameworks has emerged, lowering the barrier to systematic strategies for retail traders.[^2][^4][^9][^10][^11]

Some of the most publicized profits have come from:

- Weather markets using numerical weather prediction model data (GFS ensembles) versus Polymarket odds.[^3][^6][^12]
- High-frequency maker rebate market-making in 15-minute crypto markets.
[^9][^3]
- Near-expiry “conviction” sniping where probabilities have converged but prices still lag resolution.[^13]
- Copy-trading and wallet-following tools that mirror top performers’ trades.[^14][^15][^16]


## Evidence-Based Strategy Profiles

### 1. High-Frequency Maker Rebate Market Making (15m Crypto)

A class of bots focuses on systematically posting limit orders on both sides of short-term BTC/ETH/SOL up/down markets, capturing the bid–ask spread and potential maker rebates with minimal directional risk. The open-source `polymarket-terminal` implements a “Maker Rebate MM” strategy that automatically detects each new 15-minute market, places paired YES/NO orders around a combined cost near 0.98, and merges positions back to USDC when both sides are filled.[^3][^9]

Reported outcomes from this and similar bots:

- The `polymarket-terminal` README emphasizes continuous cycling across 15-minute markets with strict handling of ghost fills and on-chain balances, indicating the strategy has been run live and hardened against real-world failure modes.[^9]
- Kyle Walden’s “Crypto Maker Bot” posts maker limits 6–8 minutes before close on likely winning sides of 15-minute crypto markets and claims an 83 percent win rate, leveraging zero fees and maker rebates.[^3]

The edge source is microstructure: low explicit fees, predictable market schedule, and rebates that turn tight spreads plus small directional edge into compounding profits. Risk manifests as inventory imbalances, sudden price jumps, and thin books; sophisticated bots mitigate this with inventory controls and conservative size limits.[^17][^11][^9]

### 2. Model-Based Forecasting With Fractional Kelly Sizing

Several practitioners describe building quantitative prediction systems that estimate true event probabilities, then size positions using fractional Kelly to maximize long-run log growth while managing drawdowns. One Polymarket-focused quantitative system reports cross-validation accuracies around 93–95 percent with a Brier score of 0.022 on internal data, using a quarter-Kelly bet sizing rule capped at 25 percent of bankroll per trade.[^8][^7]

The Kelly fraction for a binary prediction market with current price \(q\) (interpreted as market probability) and trader belief \(p_{true}\) is:

\[ f^* = \frac{p_{true} - q}{1 - q} \]

where \(f^*\) is the fraction of bankroll to allocate when \(p_{true} > q\). In practice, live bots on Polymarket use fractional Kelly (for example 0.25×) to mitigate model error, minimum bet size constraints, and non-ergodic paths, with documentation explicitly recommending quarter-Kelly as a balance between growth and risk of ruin.[^7][^8]

Monte Carlo experiments and practitioner threads argue that naive fixed sizing or full Kelly greatly increases ruin risk in noisy edge environments, whereas fractional Kelly combined with a validated probability model can sustain compounding over long horizons.[^18][^19][^17]

### 3. Domain-Specific Informational Edge: Weather Markets

Weather markets have become a focal point because they allow traders to exploit structured data (global forecast system ensembles) that are not fully priced into market odds. Kyle Walden open-sourced a Polymarket trading bot with two strategies: a Weather Bot that trades temperature bracket markets using the GFS 31-member ensemble forecast and a Crypto Maker Bot for 15-minute markets.[^12][^3]

The Weather Bot looks for situations where the forecast implies a very high probability (for example 90 percent) but Polymarket prices the contract closer to fair coin (for example 50 percent), creating a clear expected value edge. External commentary and social posts report that similar weather bots have generated over 24k in profits, and at least one anecdote describes a weather-focused bot turning 300 units of capital into 101k in two months, though this is an extreme outlier and not independently audited.[^6][^12][^3]

### 4. Structured Copy-Trading of Top Wallets

Multiple open-source projects and guides implement copy-trading for Polymarket, tracking one or more “master” wallets and mirroring their trades with proportional sizing. The `polymarket-copy-trading-bot` by `vladmeer` automatically replicates trades from successful traders selected via leaderboards or external analytics, scaling position sizes relative to follower capital and storing history in MongoDB.[^15][^16][^14]

Another project (`polymarket-copy-trading-bot-v1` by `Trust412`) supports real-time monitoring of a target wallet with configurable parameters such as fetch intervals, retry limits, and MongoDB-based logging, showing a production-style architecture. QuickNode’s guide outlines a similar architecture using Polymarket’s CLOB and Data APIs plus WebSockets to monitor target wallets, enforce risk caps, and execute copy trades, emphasizing that robust risk filters are essential.[^20][^16][^15]

Public threads and marketing posts claim large gains (for example 66→1300 or similar testimonies) when copy-trading certain high-performing wallets or bots, often using frameworks like OpenClaw as execution backends, but these are again anecdotal, with survivorship bias and no full distribution disclosure.[^21][^22]

### 5. Single-Market Arbitrage and Structured Market Making

Analyses of Polymarket data identify “Market Rebalancing Arbitrage” within a single market and “Combinatorial Arbitrage” across multiple correlated markets. A LinkedIn write-up analyzing 86 million trades over 12 months found that combinatorial arbitrage extracted about 95,157 units of profit, whereas simple single-market arbitrage captured nearly 39.6 million, indicating that simpler structures captured roughly 0.24 percent of total arbitrage profits with far lower complexity.[^4][^1][^2]

Chinese and English-language guides branded as “Polymarket arbitrage bibles” stress that the main constraint on arbitrage profitability is order-book depth: even large apparent price discrepancies may only support profits on the order of tens of units once liquidity is considered. A concrete example given is a mispricing yielding 0.15 potential profit per dollar on a YES bundle but with only 234 units of depth, limiting maximum extractable profit to about 35.1 units.[^23][^5]

Open-source bots like `poly-maker` implement generalized liquidity provision, maintaining orders on both sides of selected markets with configurable spreads, position limits, and automated position merging tools, demonstrating that market-making infrastructure is accessible to retail quants.[^24]

### 6. Near-Expiry Conviction Sniping

The OpenClaw “Mert Sniper” skill codifies a near-expiry conviction trading strategy: filter markets by topic (for example crypto), wait until they are close to resolution, and take positions only when odds are strongly skewed (for example 60/40 or more) but the market price has not fully converged. This skill handles market discovery, trade execution, and safeguards, while encouraging users to plug in their own filters or signals for stronger edge.[^13]

This approach seeks a high hit rate by trading when most uncertainty has resolved but some microstructure inefficiency remains, effectively combining informational edge and timing. The downside is that such opportunities are sporadic and often heavily competed over by faster bots.[^22][^13]

### 7. Short-Horizon Directional Bots (5-Minute Crypto and Spikes)

A growing set of bots target very short-horizon markets such as Polymarket’s BTC 5-minute up/down contracts. One open-source bot uses Binance real-time data to compute technical indicators, predicts whether BTC will close up or down over the next 5 minutes, and times orders for the last 10 seconds of each window, using deterministic slugs based on epoch timestamps to find the right market.[^25][^26]

Other repos implement spike-detection strategies that monitor multiple markets for abrupt price moves beyond a threshold, then trade into perceived overreactions with automatic take-profit and stop-loss controls. These strategies rely on microstructure effects and short-term mean reversion but are highly sensitive to latency, slippage, and overfitting.[^27]


## Observed Performance and Sustainability

### Profits and Win Rates in the Wild

Public claims for Polymarket bots span from modest monthly returns to spectacular but rare 300→101k runs over two months in weather markets. Weather bots using GFS ensembles report win rates around 55 percent while maintaining a strong EV edge due to large probability mispricings; maker bots on crypto short-horizon markets report win rates around 83 percent where maker rebates and tight spreads amplify small directional edges.[^6][^12][^3]

Arbitrage-focused analyses show that while arbitrage profits are real and substantial in aggregate, they are heavily concentrated in simple intra-market opportunities rather than complex combinatorial structures, and the total measurable arbitrage extracted is a small slice of overall volume. This suggests that for most traders, simpler market-making or single-market mispricing strategies are more achievable than full-blown combinatorial solvers.[^1][^2][^4]

### Risk and Drawdown Characteristics

Kelly-criterion documentation for Polymarket bots highlights that full Kelly sizing leads to high drawdown risks, citing approximate probabilities of halving bankroll before doubling for full versus fractional Kelly fractions. Fractional Kelly (for example 0.25×) materially reduces the chance of severe drawdowns at the cost of slower growth, and many production setups cap per-trade exposure at a maximum of 25 percent of bankroll.[^8][^7]

Arbitrage and market-making bots explicitly warn about liquidity constraints, inventory risk, and non-atomic execution: multi-leg trades may only partially fill, leaving residual directional exposure. Combinatorial arbitrage in particular suffers from low liquidity in dependent markets and execution latency that erodes theoretical edge; empirical studies find that 62 percent of attempted combinatorial arbitrage sequences failed to generate profit despite sophisticated modeling.[^5][^1][^9]

Copy-trading carries additional risks specific to the master account: strategy changes, risk tolerance mismatches, and survivorship bias, where only exceptional performers are visible. Guides emphasize adding caps, filters, and optional ignore lists for trades that do not match follower risk preferences.[^16][^14]


## Ranking Strategies by 10→1000 Upside Potential

The table below ranks the main strategy families on two axes relevant to growing a small bankroll aggressively: practical scalability (how fast capital can grow given realistic constraints) and sustainability (likelihood of avoiding catastrophic loss over many trades). This is based on reported performance characteristics, complexity, and dependence on rare tail events.

| Rank for 10→1000 Goal | Strategy Family | Upside Potential (Qualitative) | Sustainability / Risk Profile | Key Evidence |
|-----------------------|-----------------|--------------------------------|-------------------------------|--------------|
| 1 | Weather model edge (GFS-based bots) | Very high; documented cases of 300→101k in 2 months, strong EV when forecasts show 80–90 percent vs 50 percent pricing, but highly path-dependent and capacity-limited | Medium–low; depends on model robustness, limited markets, and occasional regime shifts; fractional Kelly strongly recommended | Weather and Crypto Maker Bot repo and comments, including 55 percent win rate weather strategy and GFS ensemble use[^3]; anecdotal 300→101k weather run[^6][^12] |
| 2 | Maker rebate MM on 15m crypto markets | High; continuous opportunities with compounding, especially on zero-fee plus rebate markets; edge from spread capture and rebates rather than big directional bets | Medium; inventory and jump risk, but many small trades with limited per-trade risk and robust code can be quite durable | `polymarket-terminal` maker MM description and design[^9]; Crypto Maker Bot’s reported 83 percent win rate leveraging maker rebates[^3] |
| 3 | Quant forecasting + fractional Kelly | Medium–high; compounding can be strong over hundreds of trades, but turning 10→1000 in a month requires both genuine edge and aggressive sizing | Medium–high sustainability if sizing is conservative; drawdowns manageable with quarter-Kelly and strict caps | Quant prediction system using 93–95 percent accuracy with quarter-Kelly sizing and 25 percent caps[^7]; Kelly-based risk guidance in Polymarket bot documentation[^8][^18] |
| 4 | Near-expiry conviction sniping (Mert Sniper) | Medium–high on a small bankroll due to concentrated, high-confidence bets near resolution, especially in volatile topics | Medium; fewer trades but each can carry high variance; competition among bots compresses edges over time | OpenClaw “Mert Sniper” skill for near-expiry conviction trades and its recommended filters and caps[^13][^22] |
| 5 | Structured copy-trading of top wallets | Medium; upside bounded by master’s strategy and risk appetite; can benefit from piggybacking on sophisticated setups, but 10→1000 in a month is unlikely without extreme risk-taking by master | Medium–low; inherits master’s volatility, survivorship bias, and style drift; can mitigate via caps and selective copying | Open-source copy trading bots and QuickNode’s guide with architecture and risk controls[^14][^20][^15][^16]; anecdotal 66→1300 runs promoted via OpenClaw-related posts[^22] |
| 6 | Single-market arbitrage and generic MM | Medium on a larger bankroll but limited upside for a tiny bankroll due to liquidity and depth caps; more of a steady yield source | High; edges are structural and repeatable; risk controlled via depth and execution safeguards, but scaling is constrained | Academic analysis of arbitrage types showing 40 million in realized arbitrage profits with most from simple intra-market trades[^4][^1]; Polymarket arbitrage guide stressing depth limits[^5]; poly-maker MM repo[^24] |
| 7 | Combinatorial / cross-venue arbitrage | Low to medium for a small bankroll; heavy infra cost and competition; profits exist but are a small slice of total | Medium–high for very well engineered systems, but not practical for a small account given complexity and dependency on infrastructure | LinkedIn and academic analyses showing combinatorial strategies capturing ~0.24 percent of arbitrage profits and 62 percent of attempts failing to make money[^1][^4]; broader arbitrage overviews[^2] |

This ranking assumes a trader willing to accept substantial risk and volatility in pursuit of a 100× month, with more weight placed on “realistic path” than on “theoretical maximum payoff.” For example, a single all-in bet on a long-shot event can technically 100× capital but is closer to lottery behavior than a systematic strategy, so it is not ranked here.


## Best Strategy Combinations for Aggressive Yet Systematic Growth

For a small, risk-tolerant bankroll seeking asymmetric upside, the most promising combinations balance a high-EV niche edge with good execution and disciplined sizing:

1. **Weather Edge + Fractional Kelly + Hard Loss Caps**  
   - Use a weather bot built around GFS ensembles or similar, focusing on markets where forecast-based probability is far from market odds.[^12][^3]
   - Size positions using quarter-Kelly on estimated edge, with absolute per-trade caps (for example not more than 25 percent of bankroll) and daily stop-loss thresholds.[^7][^8]
   - This keeps the strategy systematic while still allowing for large compounding if a cluster of mispricings occurs.

2. **Maker Rebate MM on 15m Crypto + Micro Kelly Overlay**  
   - Run a maker market-making bot on 15-minute up/down markets, using maker rebates and tight spreads as the base edge.[^9][^3]
   - Overlay small directional tilts (for example slightly skewing size toward the side suggested by a simple model) sized via a tiny fractional Kelly component, so base inventory risk remains tightly controlled.[^18][^17]
   - This approach aims for steadier compounding, with upside primarily limited by market capacity rather than single outcomes.

3. **Selective Copy-Trading + Filters + Kelly-Like Caps**  
   - Instead of mirroring every trade, use copy bots that support filtering by market type, bet size, and master account behavior, and apply your own fractional Kelly caps relative to your bankroll.[^14][^20][^16]
   - Combine multiple masters with low correlation and cut copying when a wallet’s performance degrades.  
   - This can capture part of sophisticated strategies’ edge without fully inheriting their tail-risk profile.


## Open-Source Repositories and Building Blocks

The table below lists notable open-source repositories and frameworks, grouped by their primary use-case, which can serve as building blocks for custom strategies.

| Category | Repository / Resource | Role in System | Key Features / Notes |
|----------|----------------------|----------------|----------------------|
| Official CLOB and wallet SDKs | Polymarket GitHub org (for example `clob-client`, `py-clob-client`, `clob-order-utils`, `polymarket-sdk`) | Core market and wallet access | TypeScript, Python, and Rust clients for CLOB; utilities for order signing; wallet SDKs for programmatic trading; all under official Polymarket org.[^11] |
| AI agents framework | `Polymarket/agents` | AI-agent layer on top of Polymarket | Provides AI agent utilities, LLM tools, and integration with Polymarket APIs plus external news and betting data; designed to let agents reason and trade autonomously.[^10] |
| High-frequency maker MM terminal | `direkturcrypto/polymarket-terminal` | Full trading terminal with maker MM, copy trading, sniper | Implements maker rebate MM on 15m crypto markets, copy trading module, and orderbook sniper; handles ghost fill recovery, on-chain balance checks, and continuous market rotation.[^9] |
| General market-making bot | `warproxxx

---

## References

1. [Analyzing 86M Polymarket trades for combinatorial arbitrage](https://www.linkedin.com/posts/navnoorbawa_combinatorial-arbitrage-in-prediction-markets-activity-7390787738817662976-DoRa) - I analyzed 86M Polymarket trades to find combinatorial arbitrage opportunities using LLMs. 62% faile...

2. [Deconstructing Polymarket's Five Arbitrage Strategies](https://www.mexc.com/news/584334) - Author: Changan | Biteye Content Team In prediction markets, the essence of the game is not the trut...

3. [GitHub - kylecwalden/polymarket-sniper-bot | Kyle Walden - LinkedIn](https://www.linkedin.com/posts/kylewalden_github-kylecwaldenpolymarket-sniper-bot-activity-7440051736855187456-NnhD) - I open-sourced the Polymarket trading bot I've been building. It runs two strategies: 🌤️ Weather Bot...

4. [Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets](https://arxiv.org/html/2508.03474v1)

5. [Polymarket Arbitrage Bible: The Real Edge is in the Math Infrastructure](https://www.weex.com/news/detail/polymarket-arbitrage-bible-the-real-edge-is-in-the-math-infrastructure-363639) - Original Title: The Math Needed for Trading on Polymarket (Complete Roadmap)Original Author: Roan, C

6. [Bot turned $300 → $101K in 2 months on Polymarket weather markets](https://www.reddit.com/r/PredictionTrading/comments/1sgs4qy/bot_turned_300_101k_in_2_months_on_polymarket/) - Bot turned $300 → $101K in 2 months on Polymarket weather markets

7. [Building a Quantitative Prediction System for Polymarket](https://navnoorbawa.substack.com/p/building-a-quantitative-prediction) - Implements fractional Kelly criterion for position sizing. Achieved 93–95% cross-validation accuracy...

8. [Kelly Criterion - Polymarket Bot](https://www.mintlify.com/joicodev/polymarket-bot/risk/kelly-criterion) - The Kelly criterion is a mathematical formula for optimal bet sizing in scenarios with known edge. I...

9. [direkturcrypto/polymarket-terminal: Copy, Scalping & Sniper for ...](https://github.com/direkturcrypto/polymarket-terminal) - An open-source automated trading terminal for Polymarket — featuring a high-frequency maker rebate m...

10. [Trade autonomously on Polymarket using AI Agents](https://github.com/Polymarket/agents) - Trade autonomously on Polymarket using AI Agents. Contribute to Polymarket/agents development by cre...

11. [Polymarket](https://github.com/polymarket) - Polymarket. Polymarket has 99 repositories available. Follow their code on GitHub.

12. [People are making $10k–$60k trading bot weather on Polymarket. I ...](https://x.com/bySytam/status/2021612279456817532)

13. [skills/skills/adlai88/polymarket-mert-sniper/SKILL.md at main - GitHub](https://github.com/openclaw/skills/blob/main/skills/adlai88/polymarket-mert-sniper/SKILL.md) - Near-expiry conviction trading on Polymarket. Snipe markets about to resolve when the odds are heavi...

14. [vladmeer/polymarket-copy-trading-bot - GitHub](https://github.com/vladmeer/polymarket-copy-trading-bot) - Polymarket Copy Trading Bot || Polymarket trading bot. Polymarket Copy Trading Bot || Polymarket tra...

15. [GitHub - Trust412/polymarket-copy-trading-bot: Mirror master's trade and positions](https://github.com/Trust412/polymarket-copy-trading-bot) - Mirror master's trade and positions. Contribute to Trust412/polymarket-copy-trading-bot development ...

16. [Building a Polymarket Copy Trading Bot | Quicknode Guides](https://www.quicknode.com/guides/defi/polymarket-copy-trading-bot) - Build a Polymarket trading bot that tracks a target wallet, logs trades in real time, and adds posit...

17. [Adaptation of the Avellaneda-Stoikov model for Prediction ...](https://x.com/0xRicker/status/2027053618784862413) - The difference between naive Kelly and empirical Kelly with Monte Carlo is the difference between pr...

18. [0xRicker](https://x.com/0xRicker/status/2032798292128522327)

19. [Making Money in the Market: Combining Kelly Criteria and ...](https://www.youtube.com/watch?v=3wMprNtSM00) - In this video we will discuss how to combine the Kelly Criterion and Monte Carlo to create a Risk Ma...

20. [Trust412/polymarket-copy-trading-bot-v1](https://github.com/Trust412/polymarket-copy-trading-bot-v1) - The most largest prediction market - Polymarket copy trading bot: Copy master's trades and positions...

21. [Consider all the poly market and clawdbot/openclaw knowledge from this space and reveiw this ; https://x.com/argona0x/status/2019738543669621237?s=46&t=XCT8yaScHXBGPU2rOSk5Mg](https://www.perplexity.ai/search/7c1fb755-2f89-4957-8f5f-4dc9dcea5f01) - The tweet from Argona0x claims a massive overnight profit ($66 → $1,300, or ~1,800% gain) generated ...

22. [OpenClaw Polymarket Bot: Automate Trading in 2026 - FlyPix AI](https://flypix.ai/openclaw-polymarket-trading/) - OpenClaw bots made $115K/week on Polymarket. Learn how automated prediction market trading works, se...

23. [paranoiac (@webparanoiac) on X](https://x.com/webparanoiac/status/2035680334503891036)

24. [warproxxx/poly-maker - GitHub](https://github.com/warproxxx/poly-maker) - An automated market making bot for Polymarket that provides liquidity by maintaining orders on both ...

25. [TopTrenDev/openclaw-polymarket-betting-bot - GitHub](https://github.com/TopTrenDev/openclaw-polymarket-betting-bot) - OpenClaw Polymarket Betting Bot: A TypeScript skeleton bot for 5-minute prediction markets on Polyma...

26. [Polymarket BTC 5-Minute Up/Down Trading Bot](https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69) - GitHub Gist: instantly share code, notes, and snippets.

27. [Trust412/Polymarket-spike-bot-v1](https://github.com/Trust412/Polymarket-spike-bot-v1) - A high-frequency Polymarket trading bot that leverages real-time price monitoring, automated spike d...

