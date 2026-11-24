# Dice-size scaling study: runs every scenario of a TOML config (see
# configs/scaling.toml) until it converges or its episode budget is used up.
#
# Per scenario the results directory gets
#   <name>.ckpt.pkl   checkpoint (running Stats + next chunk index) for resuming
#   <name>.json       survival curve P(crosses >= k) up to the maximum + summary
# and summary.csv collects one line per scenario for the scaling-law fit.
#
# Usage (from src/game):
#   python scaling.py ../../configs/scaling.toml [--only d2 d3] [--dry-run] [--restart]

import argparse
import csv
import json
import logging
import math
import multiprocessing
import os
import pickle
import time
import tomllib
from concurrent.futures import ProcessPoolExecutor

from game import max_crosses
from log_setup import default_log_file, start_queue_listener
from row import default_min_crosses_to_lock
from simulate import (Stats, _init_worker, make_game_kwargs, max_crosses_of, report,
                      run_simulation)

logger = logging.getLogger("qwixx.scaling")

SCENARIO_KEYS = {
    "name", "enabled", "sides", "fields", "min_crosses_to_lock", "policy_max_skip",
    "max_locked_rows", "max_penalties", "max_rounds", "min_episodes", "max_episodes",
    "target_hits", "max_rel_error",
}
OPTIONAL_INT_KEYS = ("policy_max_skip", "max_locked_rows", "max_penalties", "max_rounds")
SUMMARY_FRACTIONS = (0.5, 0.75, 0.9, 1.0)
DONE = ("converged", "budget_exhausted")


# --------------------------------------------------------------------------- config

def _none(value):
    """TOML has no null: the string "none" stands for None."""
    return None if isinstance(value, str) and value.lower() == "none" else value


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    run = {"results_dir": "results", "workers": 0, "chunk_size": 100_000,
           "report_every": 100_000_000, "seed": 0}
    run.update(cfg.get("run", {}))
    run["results_dir"] = os.path.normpath(os.path.join(base_dir, run["results_dir"]))
    run["workers"] = run["workers"] or os.cpu_count()

    defaults = cfg.get("defaults", {})
    scenarios = []
    names = set()
    for raw in cfg.get("scenario", []):
        sc = {"enabled": True, **defaults, **raw}
        unknown = set(sc) - SCENARIO_KEYS
        if unknown:
            raise ValueError(f"scenario {sc.get('name')}: unknown keys {sorted(unknown)}")
        for key in OPTIONAL_INT_KEYS:
            sc[key] = _none(sc.get(key))
        _complete_and_validate(sc)
        if sc["name"] in names:
            raise ValueError(f"duplicate scenario name {sc['name']}")
        names.add(sc["name"])
        scenarios.append(sc)
    return run, scenarios


def _complete_and_validate(sc):
    name = sc.get("name")
    if not name:
        raise ValueError("every scenario needs a name")
    n = sc.get("sides")
    if not isinstance(n, int) or n < 2:
        raise ValueError(f"{name}: sides must be an integer >= 2")
    full = 2 * n - 1
    sc.setdefault("fields", full)
    sc.setdefault("min_crosses_to_lock", default_min_crosses_to_lock(n))
    if sc["fields"] > full:
        raise ValueError(f"{name}: {sc['fields']} fields but two {n}-sided dice only reach "
                         f"2..{2 * n} ({full} fields), the last field could never be crossed")
    if sc["fields"] != full:
        logger.warning("%s: %d fields instead of %d, sums above %d are useless",
                       name, sc["fields"], full, sc["fields"] + 1)
    if not 0 <= sc["min_crosses_to_lock"] <= sc["fields"] - 1:
        raise ValueError(f"{name}: min_crosses_to_lock must be within 0..{sc['fields'] - 1}")
    if sc["min_episodes"] > sc["max_episodes"]:
        raise ValueError(f"{name}: min_episodes > max_episodes")
    sc["max_crosses"] = max_crosses(sc["fields"], sc["max_locked_rows"])


def game_kwargs_of(sc):
    return make_game_kwargs(sides=sc["sides"], fields=sc["fields"], max_rounds=sc["max_rounds"],
                            max_locked_rows=sc["max_locked_rows"],
                            max_penalties=sc["max_penalties"],
                            min_crosses_to_lock=sc["min_crosses_to_lock"])


# --------------------------------------------------------------------------- convergence

def is_converged(stats, sc):
    """True once the estimate of P(perfect game) is good enough to stop early.

    Called after every finished chunk, but only once stats.n >= min_episodes.
    stats.perfect_count       games with sc["max_crosses"] crosses and 0 penalties
    stats.n                   games played so far
    stats.hits_at_least(k)    games with >= k crosses and 0 penalties
    sc["target_hits"], sc["max_rel_error"]   thresholds from the TOML
    """
    # TODO(human): decide when a scenario has seen enough perfect games.
    # Fallback until then: never converge -> every scenario runs to max_episodes.
    return False


# --------------------------------------------------------------------------- results

def _paths(results_dir, name):
    base = os.path.join(results_dir, name)
    return base + ".ckpt.pkl", base + ".json"


def _atomic_write(path, write):
    tmp = path + ".tmp"
    with open(tmp, "wb" if path.endswith(".pkl") else "w", newline="" if path.endswith(".csv") else None,
              encoding=None if path.endswith(".pkl") else "utf-8") as f:
        write(f)
    os.replace(tmp, path)


def save_checkpoint(path, sc, stats, next_idx, elapsed, status):
    state = {"game_kwargs": game_kwargs_of(sc), "policy_max_skip": sc["policy_max_skip"],
             "stats": stats, "next_idx": next_idx, "elapsed": elapsed, "status": status}
    _atomic_write(path, lambda f: pickle.dump(state, f))


def load_checkpoint(path, sc):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        state = pickle.load(f)
    if (state["game_kwargs"] != game_kwargs_of(sc)
            or state["policy_max_skip"] != sc["policy_max_skip"]):
        raise SystemExit(f"{sc['name']}: checkpoint {path} was made with different game "
                         f"settings, use --restart to discard it")
    return state


def result_dict(sc, stats, elapsed, status):
    n = stats.n
    max_c = sc["max_crosses"]
    hits = stats.perfect_count
    p = hits / n if n else 0.0
    if hits:
        rel_error = math.sqrt((1 - p) / hits)
        upper95 = p + 1.96 * math.sqrt(p * (1 - p) / n)
    else:
        rel_error = None
        upper95 = 3.0 / n if n else None   # rule of three for zero hits
    crosses = stats.crosses()
    survival = []
    remaining = n
    for k in range(max_c + 1):
        hits_ge = stats.hits_at_least(k)
        survival.append({"k": k, "fraction": k / max_c, "count": crosses[k],
                         "p_ge": remaining / n if n else 0.0,
                         "hits_ge_0pen": hits_ge, "p_ge_0pen": hits_ge / n if n else 0.0})
        remaining -= crosses[k]
    best = stats.best[3] if stats.best else None
    return {
        "scenario": {k: sc[k] for k in sorted(sc)},
        "numbers": [2, sc["fields"] + 1],
        "status": status,
        "episodes": n,
        "elapsed_s": elapsed,
        "games_per_s": n / elapsed if elapsed else None,
        "perfect_hits": hits,
        "p_perfect": p,
        "p_perfect_rel_error": rel_error,
        "p_perfect_upper95": upper95,
        "best_crosses": best["total_crosses"] if best else None,
        "best_game": {"seed": stats.best[1], "index": stats.best[2], **best} if best else None,
        "perfect_games_seed_index": stats.perfect[:100],
        "mean_crosses": sum(c * k for c, k in crosses.items()) / n if n else None,
        "locked_rows": {str(k): v for k, v in sorted(stats.locked.items())},
        "survival": survival,
    }


def write_result(path, result):
    _atomic_write(path, lambda f: json.dump(result, f, indent=1))


def write_summary(results_dir, scenarios):
    rows = []
    for sc in scenarios:
        _, json_path = _paths(results_dir, sc["name"])
        if not os.path.exists(json_path):
            continue
        with open(json_path, encoding="utf-8") as f:
            r = json.load(f)
        row = {"name": sc["name"], "sides": sc["sides"], "fields": sc["fields"],
               "max_crosses": sc["max_crosses"], "status": r["status"],
               "episodes": r["episodes"], "perfect_hits": r["perfect_hits"],
               "p_perfect": r["p_perfect"], "p_perfect_upper95": r["p_perfect_upper95"],
               "best_crosses": r["best_crosses"], "mean_crosses": r["mean_crosses"]}
        for frac in SUMMARY_FRACTIONS:
            k = math.ceil(frac * sc["max_crosses"])
            row[f"p_ge_{int(frac * 100)}pct_0pen"] = r["survival"][k]["p_ge_0pen"]
        rows.append(row)
    if not rows:
        return
    path = os.path.join(results_dir, "summary.csv")

    def write(f):
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _atomic_write(path, write)


# --------------------------------------------------------------------------- driver

def run_scenario(executor, run, sc, restart):
    ckpt_path, json_path = _paths(run["results_dir"], sc["name"])
    game_kwargs = game_kwargs_of(sc)
    if restart and os.path.exists(ckpt_path):
        os.remove(ckpt_path)
    state = load_checkpoint(ckpt_path, sc)
    if state and (state["status"] == "converged"
                  or (state["status"] == "budget_exhausted"
                      and state["stats"].n >= sc["max_episodes"])):
        print(f"[{sc['name']}] already {state['status']} after {state['stats'].n:,} games, skipped")
        return False

    stats = state["stats"] if state else Stats(max_crosses_of(game_kwargs))
    start_idx = state["next_idx"] if state else 0
    elapsed_offset = state["elapsed"] if state else 0.0
    print(f"\n[{sc['name']}] {sc['sides']}-sided dice, rows 2..{sc['fields'] + 1}, "
          f"lock after {sc['min_crosses_to_lock']}, max crosses {sc['max_crosses']}, "
          f"budget {sc['min_episodes']:,}..{sc['max_episodes']:,}"
          + (f", resuming at {stats.n:,} games" if stats.n else ""), flush=True)

    def should_stop(st):
        return st.n >= sc["min_episodes"] and is_converged(st, sc)

    def on_report(st, next_idx, elapsed):
        save_checkpoint(ckpt_path, sc, st, next_idx, elapsed, "running")
        write_result(json_path, result_dict(sc, st, elapsed, "running"))

    stats, interrupted, next_idx, elapsed = run_simulation(
        executor, sc["policy_max_skip"], sc["max_episodes"], game_kwargs, run["seed"],
        run["chunk_size"], max_in_flight=4 * run["workers"], report_every=run["report_every"],
        label=sc["name"], stats=stats, start_idx=start_idx, should_stop=should_stop,
        on_report=on_report, elapsed_offset=elapsed_offset)

    if interrupted:
        status = "interrupted"
    elif should_stop(stats):
        status = "converged"
    else:
        status = "budget_exhausted"
    save_checkpoint(ckpt_path, sc, stats, next_idx, elapsed, status)
    write_result(json_path, result_dict(sc, stats, elapsed, status))
    report(f"{sc['name']} [{status}]", stats, elapsed)
    logger.info("%s finished: %s after %d games", sc["name"], status, stats.n)
    return interrupted


def main():
    parser = argparse.ArgumentParser(description="Qwixx dice-size scaling study")
    parser.add_argument("config", help="TOML file, e.g. ../../configs/scaling.toml")
    parser.add_argument("--only", nargs="+", metavar="NAME",
                        help="run only these scenarios (also disabled ones)")
    parser.add_argument("--restart", action="store_true",
                        help="discard existing checkpoints of the selected scenarios")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    run, scenarios = load_config(args.config)
    if args.only:
        missing = set(args.only) - {sc["name"] for sc in scenarios}
        if missing:
            parser.error(f"unknown scenario(s): {sorted(missing)}")
        selected = [sc for sc in scenarios if sc["name"] in args.only]
    else:
        selected = [sc for sc in scenarios if sc["enabled"]]

    print(f"results -> {run['results_dir']}  (workers={run['workers']})")
    for sc in selected:
        print(f"  {sc['name']:<12} N={sc['sides']:<3} rows 2..{sc['fields'] + 1:<3} "
              f"lock>={sc['min_crosses_to_lock']:<3} max crosses {sc['max_crosses']:<4} "
              f"end@{sc['max_locked_rows']} locked / {sc['max_penalties']} pen  "
              f"episodes {sc['min_episodes']:,}..{sc['max_episodes']:,}  "
              f"target_hits={sc['target_hits']}")
    if args.dry_run:
        return

    os.makedirs(run["results_dir"], exist_ok=True)
    log_file = args.log_file or default_log_file("scaling")
    log_queue = multiprocessing.Queue()
    listener = start_queue_listener(log_file, log_queue, logging.INFO)
    print(f"logging to {log_file}")
    logger.info("start scaling study: config=%s run=%s scenarios=%s", args.config, run,
                [sc["name"] for sc in selected])
    executor = ProcessPoolExecutor(max_workers=run["workers"], initializer=_init_worker,
                                   initargs=(log_queue, logging.INFO))
    try:
        for sc in selected:
            interrupted = run_scenario(executor, run, sc, args.restart)
            write_summary(run["results_dir"], scenarios)
            if interrupted:
                break
        logger.info("scaling study finished")
    except Exception:
        logger.exception("scaling study aborted")
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        listener.stop()


if __name__ == "__main__":
    main()
