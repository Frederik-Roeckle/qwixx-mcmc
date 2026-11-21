# Monte Carlo runner hunting for a perfect Qwixx game:
# all 48 crosses (4 x 11 fields + 4 lock bonuses) and 0 penalties.
#
# By default every game is stopped as soon as the first penalty would be due
# and the simulation runs open ended until Ctrl+C. Every chunk only returns
# aggregated running totals, so memory stays constant. Every 10M games an
# increment is logged; the full report is printed when the run ends.
#
# Usage (from src/game):
#   python simulate.py                                    # open ended, max_skip=0
#   python simulate.py --games 1000000                    # fixed number of games
#   python simulate.py --games 10000 --no-stop-on-penalty --max-skip 0 1 2 none
#   python simulate.py --replay 1234 56                   # replay one game

import argparse
import logging
import math
import multiprocessing
import os
import random
import signal
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from game import Game
from log_setup import (default_log_file, init_worker_logging, setup_logging,
                       start_queue_listener)
from policies.policy import Policy

logger = logging.getLogger("qwixx.simulate")

MAX_CROSSES = 4 * 11 + 4  # 11 fields per row + lock bonus per row
THRESHOLDS = (30, 35, 40, 44, MAX_CROSSES)
INCREMENT_THRESHOLDS = (30, 34, 38, 40, 42, 44, 46, MAX_CROSSES)
PENALTY_TAIL = range(0, 11)
MAX_STORED_PERFECT = 1000


class Stats:
    """Running totals of many games. Small, picklable and mergeable."""

    def __init__(self):
        self.n = 0
        self.crosses_penalties = Counter()  # (total_crosses, penalties) -> count
        self.rounds = Counter()
        self.locked = Counter()
        self.score_sum = 0
        self.score_sq = 0
        self.perfect = []                   # (seed, index) of perfect games
        self.perfect_count = 0
        self.best = None                    # (key, seed, index, result)

    def add(self, result, seed, index):
        c, p = result["total_crosses"], result["penalties"]
        self.n += 1
        self.crosses_penalties[(c, p)] += 1
        self.rounds[result["rounds"]] += 1
        self.locked[result["locked_rows"]] += 1
        self.score_sum += result["score"]
        self.score_sq += result["score"] ** 2
        if c == MAX_CROSSES and p == 0:
            self.perfect_count += 1
            if len(self.perfect) < MAX_STORED_PERFECT:
                self.perfect.append((seed, index))
        key = (c, -p)
        if self.best is None or key > self.best[0]:
            self.best = (key, seed, index, result)

    def merge(self, other):
        self.n += other.n
        self.crosses_penalties.update(other.crosses_penalties)
        self.rounds.update(other.rounds)
        self.locked.update(other.locked)
        self.score_sum += other.score_sum
        self.score_sq += other.score_sq
        self.perfect_count += other.perfect_count
        room = MAX_STORED_PERFECT - len(self.perfect)
        self.perfect.extend(other.perfect[:max(room, 0)])
        if other.best is not None and (self.best is None or other.best[0] > self.best[0]):
            self.best = other.best

    def crosses(self):
        hist = Counter()
        for (c, _), k in self.crosses_penalties.items():
            hist[c] += k
        return hist

    def penalties(self):
        hist = Counter()
        for (_, p), k in self.crosses_penalties.items():
            hist[p] += k
        return hist


def _hist_stats(hist):
    n = sum(hist.values())
    mean = sum(v * k for v, k in hist.items()) / n
    var = sum(k * (v - mean) ** 2 for v, k in hist.items()) / n
    return mean, math.sqrt(var), min(hist), max(hist)


def _init_worker(queue, level):
    # Ctrl+C is handled by the main process only; workers finish their chunk
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    init_worker_logging(queue, level)


def run_batch(max_skip, n_games, max_rounds, seed, stop_on_penalty):
    """Worker: plays `n_games` games and returns their aggregated Stats."""
    random.seed(seed)
    logger.debug("batch start: max_skip=%s games=%d seed=%d", max_skip, n_games, seed)
    policy = Policy(max_skip=max_skip)
    stats = Stats()
    for index in range(n_games):
        game = Game(6, 12, policy=policy, max_rounds=max_rounds,
                    stop_on_penalty=stop_on_penalty)
        stats.add(game.play(), seed, index)
    return stats


def log_increment(max_skip, stats, elapsed):
    crosses = stats.crosses()
    n = stats.n
    tail = "  ".join(
        f">={k}: {sum(v for c, v in crosses.items() if c >= k)}" for k in INCREMENT_THRESHOLDS)
    _, seed, index, result = stats.best
    msg = (f"max_skip={max_skip}: {n:,} games, {elapsed:,.0f}s, {n / elapsed:,.0f} games/s | "
           f"perfect: {stats.perfect_count} | best: {result['total_crosses']} crosses "
           f"{result['penalties']} penalties (seed={seed} index={index}) | games with {tail}")
    logger.info(msg)
    print("  " + msg, flush=True)


def run_simulation(executor, max_skip, n_games, max_rounds, seed, chunk_size,
                   max_in_flight, report_every, stop_on_penalty):
    """Runs `n_games` games (None = open ended until Ctrl+C).
    Returns (stats, interrupted)."""
    logger.info("max_skip=%s: %s games, chunks of %d, stop_on_penalty=%s", max_skip,
                "open ended" if n_games is None else f"{n_games:,}", chunk_size,
                stop_on_penalty)

    total = Stats()
    pending = {}
    next_idx = 0
    submitted = 0
    next_report = report_every
    start = time.perf_counter()
    interrupted = False

    try:
        while True:
            # keep a bounded number of chunks queued instead of submitting all at once
            while len(pending) < max_in_flight and (n_games is None or submitted < n_games):
                size = chunk_size if n_games is None else min(chunk_size, n_games - submitted)
                future = executor.submit(run_batch, max_skip, size, max_rounds,
                                         seed + next_idx, stop_on_penalty)
                pending[future] = next_idx
                next_idx += 1
                submitted += size
            if not pending:
                break

            # timeout so Ctrl+C is noticed promptly on Windows
            done, _ = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for future in done:
                idx = pending.pop(future)
                try:
                    chunk = future.result()
                except Exception:
                    logger.exception("chunk %d (seed %d) failed", idx, seed + idx)
                    raise
                if chunk.perfect_count:
                    logger.info("PERFECT GAME(S) found in chunk %d (seed, index): %s",
                                idx, chunk.perfect[:10])
                    print(f"  PERFECT game(s) found (seed, index): {chunk.perfect[:10]}",
                          flush=True)
                total.merge(chunk)

            if total.n >= next_report:
                log_increment(max_skip, total, time.perf_counter() - start)
                while next_report <= total.n:
                    next_report += report_every
    except KeyboardInterrupt:
        interrupted = True
        for future in pending:
            future.cancel()
        logger.warning("interrupted by user after %d games", total.n)
        print("\n  interrupted, writing report ...", flush=True)

    return total, interrupted


def report(max_skip, stats, elapsed):
    n = stats.n
    if n == 0:
        print("no games finished")
        return
    crosses = stats.crosses()
    penalties = stats.penalties()

    lines = [f"=== max_skip = {max_skip}  ({n:,} games, {elapsed:,.1f}s, "
             f"{n / elapsed:,.0f} games/s) ==="]
    m, s, lo, hi = _hist_stats(crosses)
    lines.append(f"crosses    mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}  (max possible {MAX_CROSSES})")
    m, s, lo, hi = _hist_stats(stats.rounds)
    lines.append(f"rounds     mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}")
    m, s, lo, hi = _hist_stats(penalties)
    lines.append(f"penalties  mean {m:6.2f}  std {s:5.2f}  min {lo:3d}  max {hi:3d}")
    score_mean = stats.score_sum / n
    score_std = math.sqrt(max(stats.score_sq / n - score_mean ** 2, 0))
    lines.append(f"score      mean {score_mean:6.2f}  std {score_std:5.2f}")
    lines.append("locked rows: " + "  ".join(f"{k}: {stats.locked[k] / n:6.2%}" for k in range(5)))

    lines.append("penalty tail (games with exactly / at most k penalties):")
    cumulative = 0
    for k in PENALTY_TAIL:
        cumulative += penalties[k]
        lines.append(f"  {k:3d} | {penalties[k]:>14,d}  {penalties[k] / n:.3e}   "
                     f"<= {cumulative:>14,d}  {cumulative / n:.3e}")

    lines.append(f"PERFECT games (all {MAX_CROSSES} crosses, 0 penalties): "
                 f"{stats.perfect_count:,} of {n:,} ({stats.perfect_count / n:.3e})")
    if stats.perfect:
        lines.append(f"  first perfect games (seed, index): {stats.perfect[:20]}")
    _, seed, index, result = stats.best
    lines.append(f"best game: seed={seed} index={index} -> {result}")

    # histogram with survival column: P(crosses >= k) is the curve to
    # extrapolate towards 48 if no perfect game was found
    lines.append("total crosses:   k |          count |    P(=k)  |   P(>=k)")
    survival = n
    for k in range(min(crosses), max(crosses) + 1):
        lines.append(f"                {k:3d} | {crosses[k]:>14,d} | {crosses[k] / n:.3e} | "
                     f"{survival / n:.3e}")
        survival -= crosses[k]

    print("\n" + "\n".join(lines))
    for line in lines:
        logger.info(line)


def replay(max_skip, max_rounds, stop_on_penalty, seed, index):
    """Re-plays game `index` of the chunk with `seed` and logs every round."""
    log_file = default_log_file(f"replay_{seed}_{index}")
    setup_logging(log_file, logging.DEBUG)
    game_logger = logging.getLogger("qwixx.game")
    random.seed(seed)
    policy = Policy(max_skip=max_skip)

    def new_game():
        return Game(6, 12, policy=policy, max_rounds=max_rounds,
                    stop_on_penalty=stop_on_penalty)

    game_logger.setLevel(logging.WARNING)  # skip the games before the target
    for _ in range(index):
        new_game().play()
    game_logger.setLevel(logging.NOTSET)
    game = new_game()
    print(game.play())
    game._print_state()
    print(f"round-by-round log: {log_file}")


def parse_max_skip(value):
    return None if value.lower() == "none" else int(value)


def main():
    parser = argparse.ArgumentParser(description="Qwixx Monte Carlo simulation")
    parser.add_argument("--games", type=int, default=None,
                        help="number of games per setting (default: open ended until Ctrl+C)")
    parser.add_argument("--max-skip", type=parse_max_skip, nargs="+", default=[0])
    parser.add_argument("--stop-on-penalty", action=argparse.BooleanOptionalAction,
                        default=True, help="end a game at its first penalty (default: on)")
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--chunk-size", type=int, default=100_000)
    parser.add_argument("--report-every", type=int, default=10_000_000,
                        help="log an increment every N games (default 10M)")
    parser.add_argument("--replay", type=int, nargs=2, metavar=("SEED", "INDEX"),
                        help="replay a single game (uses the first --max-skip value)")
    parser.add_argument("--log-file", default=None,
                        help="default: logs/simulate_<timestamp>.log")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="DEBUG logs every round of every game (huge files!)")
    args = parser.parse_args()

    if args.replay:
        replay(args.max_skip[0], args.max_rounds, args.stop_on_penalty, *args.replay)
        return
    if args.games is None and len(args.max_skip) > 1:
        parser.error("an open ended run takes exactly one --max-skip value (or set --games)")

    log_file = args.log_file or default_log_file("simulate")
    level = getattr(logging, args.log_level)
    log_queue = multiprocessing.Queue()
    listener = start_queue_listener(log_file, log_queue, level)

    print(f"logging to {log_file}")
    print(f"{'open ended (Ctrl+C to stop)' if args.games is None else f'{args.games:,} games'}"
          f" per setting, workers={args.workers}, stop_on_penalty={args.stop_on_penalty}, "
          f"max_rounds={args.max_rounds}, seed={args.seed}")
    logger.info("start simulation: %s", vars(args))
    executor = ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker,
                                   initargs=(log_queue, level))
    try:
        for max_skip in args.max_skip:
            start = time.perf_counter()
            stats, interrupted = run_simulation(
                executor, max_skip, args.games, args.max_rounds, args.seed,
                args.chunk_size, max_in_flight=4 * args.workers,
                report_every=args.report_every, stop_on_penalty=args.stop_on_penalty)
            report(max_skip, stats, time.perf_counter() - start)
            if interrupted:
                break
        logger.info("simulation finished")
    except Exception:
        logger.exception("simulation aborted")
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        listener.stop()


if __name__ == "__main__":
    main()
