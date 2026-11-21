# defines the policy which should be followed to play the game
#
# Greedy policy: for every possible dice combination compute how many fields
# would be skipped in the target row and take the move with the smallest skip.
# A move is only taken if it skips at most `max_skip` fields
# (max_skip=None -> always take the best legal move).

WHITE_DICES = ("W1", "W2")


class Policy():

    def __init__(self, max_skip=None):
        self.max_skip = max_skip

    @staticmethod
    def _dice_values(dices):
        dices_values = {}
        for dice in dices:
            dices_values = dices_values | dice._get_repr()
        return dices_values

    def _best(self, candidates):
        """candidates: list of (order_idx, row, number). Returns (row, number) or None."""
        best = None
        best_key = None
        for order_idx, row, number in candidates:
            if not row.can_cross(number):
                continue
            skip = row.skip_count(number)
            if self.max_skip is not None and skip > self.max_skip:
                continue
            # smallest skip first, then the row closer to locking, then fixed order
            key = (skip, -row.crosses, order_idx)
            if best_key is None or key < best_key:
                best_key = key
                best = (row, number)
        return best

    def choose_white(self, values, rows):
        """Step 1: sum of both white dices, may be crossed in any row."""
        sum_of_whites = values["W1"] + values["W2"]
        return self._best([(i, row, sum_of_whites) for i, row in enumerate(rows)])

    def choose_color(self, values, rows):
        """Step 2: one white dice + the dice of the row's color."""
        candidates = []
        for i, row in enumerate(rows):
            for w in WHITE_DICES:
                candidates.append((i, row, values[w] + values[row.color]))
        return self._best(candidates)

    def act(self, dices, rows):
        """Plays a full turn (white step, then color step). Returns the crosses made."""
        values = self._dice_values(dices)
        moves = []
        for choose in (self.choose_white, self.choose_color):
            move = choose(values, rows)
            if move is not None:
                row, number = move
                row.cross(number)
                moves.append((row.color, number))
        return moves
