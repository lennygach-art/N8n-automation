n8n Automation

This project is a self-hosted automation stack that brings together n8n, MetaTrader 5 (MT5), and Python tools for coordinating trading-strategy backtests and exporting historical market data. It includes MQL5 Expert Advisors (EAs) for testing strategies in MT5. It is an automation and research toolkit—not a guarantee that a strategy is profitable.

## How it works

Docker Compose runs the n8n service, an MT5 container, an MT5 history-bridge service, and an ngrok tunnel. n8n’s persistent data is stored in a Docker volume, while the shared workspace allows services to exchange request files, reports, and data. Configuration and credentials should be supplied locally through environment variables rather than committed to the repository.

Python scripts use file-based queues to pass requests between automation tools and MT5:

- **Backtesting:** A request helper places a backtest request in the shared queue. The backtest watcher prepares an MT5 Strategy Tester run and collects its report. The watcher is **not started automatically by the current Compose configuration**; it must be started separately for this flow to process requests.
- **Historical data export:** A Python bridge passes a date-range request to an MT5 EA. The EA must be installed and attached to a chart in MT5. It exports M1 price data—including OHLC prices, volume, and spread—which the bridge saves to the shared workspace along with a status report.

## Included strategy and integration code

The repository includes MQL5 EAs, Python queue and data-transfer scripts, and Docker configuration. The EAs contain strategy logic for MT5 testing; they are separate from the automation services and must be configured and run in MT5. Review and test any EA carefully before using it with a live trading account.

## Security and deployment notes

Keep `.env`, MT5 account/configuration data, n8n’s persistent data, generated reports, and other private runtime files out of Git. The ngrok tunnel can make n8n reachable from outside your computer, so protect the instance and only expose it when needed. Any external services referenced in the configuration, such as the sandbox API, must be set up separately.
