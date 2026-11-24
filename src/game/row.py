

# Standard Qwixx: 5 crosses are needed before the last field may be crossed.
# With N-sided dice a row has F = 2N - 1 fields (numbers 2..2N); the rule
# "half of the F - 1 non-last fields" gives (F - 1) / 2 = N - 1, i.e. 5 for N = 6.
MIN_CROSSES_TO_LOCK = 5


def default_min_crosses_to_lock(no_sides):
    return max(no_sides - 1, 1)


class Row():

    def __init__(self, no_numbers, color, order="asc", min_crosses_to_lock=MIN_CROSSES_TO_LOCK):
        self.no_numbers = no_numbers
        self.color = color
        self.order = order
        self.min_crosses_to_lock = min_crosses_to_lock
        if self.order == "asc":
            self.largest_crossed_number = 1
        else:
            self.largest_crossed_number = self.no_numbers + 1
        self.row_numbers = [i for i in range(2, self.no_numbers + 1)]

        if self.order == "desc":
            self.row_numbers = sorted(self.row_numbers, reverse=True)

        self.row_state = {number: 0 for number in self.row_numbers}
        self._index = {number: i for i, number in enumerate(self.row_numbers)}
        self._last_index = len(self.row_numbers) - 1

        # index (into row_numbers) of the last crossed field, -1 = nothing crossed
        self.position = -1
        self.crosses = 0
        self.is_locked = False
        self.is_complete = False

    def _get_repr(self):
        return self.row_state

    def _is_last(self, number):
        return self._index.get(number) == self._last_index

    def skip_count(self, number):
        """Number of fields that would be lost by crossing `number`."""
        return self._index[number] - self.position - 1

    def can_cross(self, number):
        if self.is_locked:
            return False
        idx = self._index.get(number)
        if idx is None or idx <= self.position:
            return False
        if idx == self._last_index and self.crosses < self.min_crosses_to_lock:
            return False
        return True

    def cross(self, number):
        assert self.can_cross(number), f"illegal cross {number} in row {self.color}"
        self.row_state[number] = 1
        self.position = self._index[number]
        self.largest_crossed_number = number
        self.crosses += 1
        if self._is_last(number):
            # crossing the last number locks the row and gives the lock bonus cross
            self.is_locked = True
            self.is_complete = True
            self.crosses += 1

    def _write_number(self, number):
        self.cross(number)
        return 0

    def is_finished(self):
        """True if no further cross is possible in this row."""
        if self.is_locked:
            return True
        # only the last field is left but the row can never be locked
        return (self.position >= self._last_index - 1
                and self.crosses < self.min_crosses_to_lock)

    def score(self):
        return self.crosses * (self.crosses + 1) // 2

    def _is_row_full(self):
        return self.is_locked
