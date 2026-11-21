# Monte Carlo runner: plays many games in parallel for different
# greediness levels (max_skip) and compares the number of crosses.
#
# Usage (from src/game):
#   python simulate.py --games 10000 --max-skip 0 1 2 3 none --seed 1
#   python simulate.py --games 10000 --max-rounds 40

import argparse
import os
import random
import statistics
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

from game import Game
from policies.policy import Policy

MAX_CROSSES = 4 * 11 + 4  # 11 fields per row + lock bonus per row
THRESHOLDS = (30, 35, 40, 44, MAX_CROSSES)


def run_batch(max_skip, n_games, max_rounds, seed):
    """Worker: plays `n_games` games and returns their result dicts."""
    random.seed(seed)
    policy = Policy(max_skip=max_skip)
    return [Game(6, 12, policy=policy, max_rounds=max_rounds).play() for _ in range(n_games)]


def run_simulation(executor, max_skip, n_games, max_rounds, seed, chunk_size):
    chunks = []
    remaining = n_games
    while remaining > 0:
        chunks.append(min(chunk_size, remaining))
        remaining -= chunks[-1]

    futures = {
        executor.submit(run_batch, max_skip, size, max_rounds, seed + idx): idx
        for idx, size in enumerate(chunks)
    }
    by_chunk = {}
    for future in as_completed(futures):
        by_chunk[futures[future]] = future.result()
    return [r for idx in sorted(by_chunk) for r in by_chunk[idx]]


def _stats(values):
    return statistics.mean(values), statistics.pstdev(values), min(values), max(values)


def report(max_skip, results, elapsed):
    n = len(results)
    crosses = [r["total_crosses"] for r in results]
    rounds = [r["rounds"] for r in results]
    penalties = [r["penalties"] for r in results]
    scores = [r["score"] for r in results]
    locked = Counter(r["locked_rows"] for r in results)

    print(f"\n=== max_skip = {max_skip}  ({n} games, {elapsed:.1f}s) ===")
    m, s, lo, hi = _stats(crosses)
    print(f"crosses    mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}  (max possible {MAX_CROSSES})")
    m, s, lo, hi = _stats(rounds)
    print(f"rounds     mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}")
    m, s, lo, hi = _stats(penalties)
    print(f"penalties  mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}")
    print(f"score      mean {statistics.mean(scores):6.2f}")
    print("locked rows: " + "  ".join(f"{k}: {locked[k] / n:6.2%}" for k in range(5)))
    print("P(crosses >= k): " + "  ".join(
        f"{k}: {sum(c >= k for c in crosses) / n:7.3%}" for k in THRESHOLDS))

    hist = Counter(crosses)
    peak = max(hist.values())
    print("histogram of total crosses:")
    for k in range(min(hist), max(hist) + 1):
        bar = "#" * round(50 * hist[k] / peak)
        print(f"  {k:3d} | {hist[k] / n:7.3%} {bar}")


def parse_max_skip(value):
    return None if value.lower() == "none" else int(value)


def main():
    parser = argparse.ArgumentParser(description="Qwixx Monte Carlo simulation")
    parser.add_argument("--games", type=int, default=2e8)
    parser.add_argument("--max-skip", type=parse_max_skip, nargs="+",
                        default=[None])
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args()

    print(f"{args.games} games per setting, workers={args.workers}, "
          f"max_rounds={args.max_rounds}, seed={args.seed}")
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for max_skip in args.max_skip:
            start = time.perf_counter()
            results = run_simulation(executor, max_skip, args.games, args.max_rounds,
                                     args.seed, args.chunk_size)
            report(max_skip, results, time.perf_counter() - start)


if __name__ == "__main__":
    main()
