# Idea:
# I was wondering what the likelihood of having a perfect
# game in QWIXX would be?

# Game setup:
# 2x white 6-sided dices (w1, w2), one dice in blue(b1), red(r1), green(g1) and yellow(y1)
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
# Deviation from the official rules (on purpose, to compare policies):
# the game does NOT end after two locked rows or four penalties. It runs
# until no row can take another cross (or an optional round cap is hit).
# The lock rule applies: the last number of a row needs >= 5 crosses
# in that row, crossing it locks the row and adds a bonus cross.

import logging

from row import Row
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


class Game():

    def __init__(self, no_sides_dice=6, no_numbers=12, policy=None, max_rounds=None,
                 stop_on_penalty=False):
        self.no_numbers = no_numbers
        self.no_sides_dice = no_sides_dice
        self.dices = [Dice(color, self.no_sides_dice) for color in DICE_COLORS]
        self.rows = [Row(self.no_numbers, color, order=ROW_ORDER[color]) for color in ROW_COLORS]
        self.policy = policy if policy is not None else Policy()
        self.max_rounds = max_rounds
        # end the game as soon as the first penalty is due (hunting perfect games)
        self.stop_on_penalty = stop_on_penalty
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

            if self.penalties and self.stop_on_penalty:
                break

        result = self.result()
        if debug:
            logger.debug("game over: %s", result)
        return result

    def _is_game_over(self):
        if self.max_rounds is not None and self.rounds >= self.max_rounds:
            return True
        return all(row.is_finished() for row in self.rows)

    def result(self):
        crosses_per_row = {row.color: row.crosses for row in self.rows}
        return {
            "crosses_per_row": crosses_per_row,
            "total_crosses": sum(crosses_per_row.values()),
            "locked_rows": sum(row.is_locked for row in self.rows),
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
    g = Game(6, 12, policy=Policy(max_skip=1))
    print(g.play())
    g._print_state()
