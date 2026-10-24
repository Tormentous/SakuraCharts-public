# Sakuracharts

> [!WARNING]
> **This project was largely AI-generated (AI slop warning). Not financial advice. Use at your own risk.**
> Expect rough edges, dead code paths and bugs. Nothing here is a trading recommendation, and paper results mean nothing about live results.

Sakuracharts is a small self-hosted charting and bar-replay app for 1-minute OHLCV data, in the style of TradingView's bar replay:

- candlestick chart (1m / 5m / 15m / 1h / 4h) using [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)
- **bar replay**: pick a start bar (date, first bar, random), play / pause / step, speed 0.5x-500x
- drawing tools: trendline, horizontal line, fib, long / short position, text, ruler, magnet, lock
- **paper trading** inside replay or on the latest bar: market / limit / stop orders, bracket presets, right-click order menu, positions and PnL
- trade **journal** with notes, tags, ratings and screenshots; CSV / JSON export and CSV import
- themes (Sakura, Glacier, Minty, Starry), layouts and preferences saved on the server
- password login (PBKDF2-hashed, signed session cookie)

It ships **no market data and no trading strategies**. A synthetic random-walk generator is included so it runs out of the box.

## Install and run

Needs Python 3.9+ (standard library only) and a modern browser. The page loads Lightweight Charts, Font Awesome and Google Fonts from public CDNs, so the browser needs internet access.

```bash
git clone <this repo> sakuracharts && cd sakuracharts
python3 tools/make_sample_data.py          # writes data/sample-1m.csv (fake data, ~20 days of 1m bars)
python3 sakuracharts/server.py             # http://127.0.0.1:8765
```

On first start a random password is printed in the terminal (only a salted hash is stored in `~/.sakuracharts/auth.json`). Change it in Settings, or pick your own:

```bash
SAKURA_PASS='choose-a-password' python3 sakuracharts/server.py --port 8765 --no-open
```

If `data/sample-1m.csv` is missing the server generates it on start.

### Your own data

Load any 1-minute CSV with the **+** button in the top bar, or start with `python3 sakuracharts/server.py path/to/bars.csv`.
Columns: `time` (or `datetime` / `timestamp` / `date`; ISO-8601, UTC if no zone, or epoch seconds/ms), `open`, `high`, `low`, `close`, optional `volume`.

### Options

| Env / flag | Meaning |
|---|---|
| `--host`, `--port` | listen address (default `127.0.0.1:8765`) |
| `--no-open` | do not open a browser tab |
| `SAKURA_PASS` | password from the environment (not stored) |
| `SAKURA_HOME` | where auth, prefs and journal are kept (default `~/.sakuracharts`) |
| `SAKURA_DATA` | data folder (default `./data`) |

Keep it on localhost. If you expose it, put it behind an HTTPS reverse proxy.

## Layout

```
sakuracharts/server.py      stdlib HTTP server + JSON API
sakuracharts/static/        index.html (the whole app) and login.html
sakuracharts/assets/        icons, wordmark, theme backgrounds (see CREDITS.md)
tools/make_sample_data.py   synthetic random-walk 1m OHLCV generator
```

## License

MIT, see [LICENSE](LICENSE). Theme photos are third-party, see [CREDITS.md](sakuracharts/assets/CREDITS.md).
Lightweight Charts is © TradingView, Inc., Apache-2.0.
