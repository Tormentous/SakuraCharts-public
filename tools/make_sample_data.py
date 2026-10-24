#!/usr/bin/env python3
"""Generate synthetic 1-minute OHLCV bars (a random walk) so Sakuracharts runs out of the box.

The data is FAKE. It is not market data and says nothing about any real instrument.
Usage: python tools/make_sample_data.py [--days 20] [--start 20000] [--seed 42] [--out data/sample-1m.csv]
"""
import argparse, csv, math, random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(days=20, start=20000.0, seed=42, tick=0.25, vol=3.0):
    rnd = random.Random(seed)
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=days)
    end = t + timedelta(days=days)
    p = start
    drift_phase = rnd.random() * 6.28
    while t < end:
        if t.weekday() < 5:                                   # weekdays only, 24h like a futures feed
            i = int(t.timestamp() // 60)
            sigma = vol * (1.0 + 0.6 * math.sin(i / 720.0 + drift_phase) ** 2)   # slow volatility cycle
            o = p
            c = o + rnd.gauss(0.02, sigma)
            h = max(o, c) + abs(rnd.gauss(0, sigma * 0.6))
            l = min(o, c) - abs(rnd.gauss(0, sigma * 0.6))
            q = lambda x: round(round(x / tick) * tick, 2)
            o, h, l, c = q(o), q(h), q(l), q(c)
            yield [t.strftime("%Y-%m-%dT%H:%M:%SZ"), o, max(h, o, c), min(l, o, c), c, rnd.randint(50, 2500)]
            p = c
        t += timedelta(minutes=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=20); ap.add_argument("--start", type=float, default=20000.0)
    ap.add_argument("--seed", type=int, default=42); ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "sample-1m.csv"))
    a = ap.parse_args()
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "open", "high", "low", "close", "volume"])
        for row in generate(a.days, a.start, a.seed):
            w.writerow(row); n += 1
    print(f"wrote {n} synthetic 1m bars to {out}")


if __name__ == "__main__":
    main()
