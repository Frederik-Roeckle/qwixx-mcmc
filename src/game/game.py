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
#   4. checkBox: add one cross to the state roundsWithoutPoints
# Game ends when a) two color tracks closed or b) roundsWithoutPoints == 4



# define dice class (no. of sides, color)

# define row class (no of numbers, color, order/unordered/asc/desc)

# define game class which aggregates dices and rows

from row import Row
from dice import Dice
from policies.policy import Policy


ROW_COLORS = ["B1", "R1", "G1", "Y1"]
ROW_ORDER = {"B1": "desc",
             "R1": "asc",
             "G1": "desc",
             "Y1": "asc"}
DICE_COLORS = ROW_COLORS.copy()
DICE_COLORS.extend(["W1", "W2"])
print(ROW_COLORS)
print(DICE_COLORS)

class Game():

    def __init__(self, no_sides_dice, no_numbers):
        self.no_numbers = no_numbers
        self.no_sides_dice = no_sides_dice
        self.dices = [Dice(color, self.no_sides_dice) for color in DICE_COLORS]
        self.rows = [Row(self.no_numbers, color, order=ROW_ORDER[color]) for color in ROW_COLORS]
        self.policy = Policy()


    def play(self):
        while not self._is_game_over():
            # throw dices
            for dice in self.dices:
                dice.throw()

            # act on the dice results
            self.policy.act(self.dices, self.rows)


    def _is_game_over(self):
        counter = 0
        for row in self.rows:
            if row._is_row_full():
                counter += 1
        if counter == 2: return True
        return False


    def _print_state(self):
        print(f"dices: {self.dices}")
        print(f"rows: {self.rows}")


if __name__ == "__main__":
    g = Game(6,12)
    g.play()