# Idea:
# I was wondering what the likelihood of having a perfect
# game in QWIXX would be?

# Game setup:
# 2x white N-sided dices (w1, w2), one dice in blue(b1), red(r1), green(g1) and yellow(y1)
# Every row holds the numbers 2..2N (F = 2N - 1 fields), N = 6 is the original game.
# per round:
#   1. you throw all dices
#   2. either (checkNumber) or (checkBox)
#   3. def chechNumber:
#   3.1 the sum of w1 and w2
#   3.2 sum of (w1 xor w2) and (b1 xor r1 xor g1 xor y1)
# either step 3.1 and 3.2 in order or only 3.1 or 3.2.
# if none:
#   4. checkBox: add one cross to the state roundsWithoutPoints (penalty)
#
# End of game (official rules, both configurable):
#   - as soon as `max_locked_rows` (default 2) rows are locked. Locking a row
#     removes its colored dice from the game. Both actions of the turn in which
#     the 2nd row gets locked still count, so up to 3 rows can end up locked.
#   - as soon as `max_penalties` (default 4) penalties are collected
#     (max_penalties=1 ends the game at the first penalty, perfect game hunt).
#   - when no row can take another cross, or an optional round cap is hit.
# The lock rule applies: the last number of a row needs >= min_crosses_to_lock
# crosses in that row, crossing it locks the row and adds a bonus cross.

import logging

from row import Row, default_min_crosses_to_lock
from dice import Dice
from policies.policy import Policy

logger = logging.getLogger("qwixx.game")


ROW_COLORS = ["B1", "R1", "G1", "Y1"]
ROW_ORDER = {"B1": "desc",
             "R1": "asc",
             "G1": "desc",
             "Y1": "asc"}
DICE_COLORS = ROW_COLORS.copy()
DICE_COLORS.extend(["W1", "W2"])
PENALTY_POINTS = 5
MAX_LOCKED_ROWS = 2
MAX_PENALTIES = 4


def fields_per_row(no_sides_dice):
    """A row holds every possible sum of two dices: 2..2N."""
    return 2 * no_sides_dice - 1


def max_crosses(fields, max_locked_rows=MAX_LOCKED_ROWS):
    """Largest number of crosses reachable with `fields` fields per row.

    The game stops after the turn that locks the `max_locked_rows`-th row and a
    turn has at most two actions, so at most max_locked_rows + 1 rows can be
    locked (F + 1 crosses each). Every other row stops one before its last field.
    6-sided dices: 46 with the official rule, 48 without it (max_locked_rows=None).
    """
    n_rows = len(ROW_COLORS)
    if max_locked_rows is None:
        locked = n_rows
    else:
        locked = min(n_rows, max_locked_rows + 1)
    return locked * (fields + 1) + (n_rows - locked) * (fields - 1)


class Game():

    def __init__(self, no_sides_dice=6, no_numbers=None, policy=None, max_rounds=None,
                 stop_on_penalty=False, max_locked_rows=MAX_LOCKED_ROWS,
                 max_penalties=MAX_PENALTIES, min_crosses_to_lock=None):
        self.no_sides_dice = no_sides_dice
        # highest number of a row, 2N by default (12 for 6-sided dices)
        self.no_numbers = no_numbers if no_numbers is not None else 2 * no_sides_dice
        if min_crosses_to_lock is None:
            min_crosses_to_lock = default_min_crosses_to_lock(no_sides_dice)
        self.min_crosses_to_lock = min_crosses_to_lock
        self.dices = [Dice(color, self.no_sides_dice) for color in DICE_COLORS]
        self.rows = [Row(self.no_numbers, color, order=ROW_ORDER[color],
                         min_crosses_to_lock=min_crosses_to_lock)
                     for color in ROW_COLORS]
        self.policy = policy if policy is not None else Policy()
        self.max_rounds = max_rounds
        self.max_locked_rows = max_locked_rows
        # stop_on_penalty is kept for backwards compatibility: end at the first penalty
        self.max_penalties = 1 if stop_on_penalty else max_penalties
        self.penalties = 0
        self.rounds = 0

    def play(self):
        debug = logger.isEnabledFor(logging.DEBUG)
        while not self._is_game_over():
            self.rounds += 1
            for dice in self.dices:
                dice.throw()

            moves = self.policy.act(self.dices, self.rows)
            if not moves:
                self.penalties += 1

            if debug:
                dice_values = {d.color: d.face_value for d in self.dices}
                logger.debug("round %d dice=%s moves=%s%s", self.rounds, dice_values,
                             moves, "" if moves else " -> penalty")

            self._remove_dices_of_locked_rows()

        result = self.result()
        if debug:
            logger.debug("game over: %s", result)
        return result

    def _remove_dices_of_locked_rows(self):
        locked = {row.color for row in self.rows if row.is_locked}
        if locked:
            self.dices = [d for d in self.dices if d.color not in locked]

    def locked_rows(self):
        return sum(row.is_locked for row in self.rows)

    def _is_game_over(self):
        if self.max_rounds is not None and self.rounds >= self.max_rounds:
            return True
        if self.max_penalties is not None and self.penalties >= self.max_penalties:
            return True
        if self.max_locked_rows is not None and self.locked_rows() >= self.max_locked_rows:
            return True
        return all(row.is_finished() for row in self.rows)

    def result(self):
        crosses_per_row = {row.color: row.crosses for row in self.rows}
        return {
            "crosses_per_row": crosses_per_row,
            "total_crosses": sum(crosses_per_row.values()),
            "locked_rows": self.locked_rows(),
            "penalties": self.penalties,
            "rounds": self.rounds,
            "score": sum(row.score() for row in self.rows) - PENALTY_POINTS * self.penalties,
        }

    def _print_state(self):
        print(f"dices: {[d._get_repr() for d in self.dices]}")
        for row in self.rows:
            print(f"{row.color}: {row._get_repr()}")


if __name__ == "__main__":
    from log_setup import default_log_file, setup_logging

    log_file = default_log_file("game")
    setup_logging(log_file, logging.DEBUG)
    print(f"logging to {log_file}")
    g = Game(6, policy=Policy(max_skip=1))
    print(g.play())
    g._print_state()
