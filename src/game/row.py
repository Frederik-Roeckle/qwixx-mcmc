

MIN_CROSSES_TO_LOCK = 5


class Row():

    def __init__(self, no_numbers, color, order="asc"):
        self.no_numbers = no_numbers
        self.color = color
        self.order = order
        if self.order == "asc":
            self.largest_crossed_number = 1
        else:
            self.largest_crossed_number = self.no_numbers + 1
        self.row_numbers = [i for i in range(2, self.no_numbers + 1)]

        if self.order == "desc":
            self.row_numbers = sorted(self.row_numbers, reverse=True)

        self.row_state = {number: 0 for number in self.row_numbers}
        self._index = {number: i for i, number in enumerate(self.row_numbers)}

        # index (into row_numbers) of the last crossed field, -1 = nothing crossed
        self.position = -1
        self.crosses = 0
        self.is_locked = False
        self.is_complete = False

    def _get_repr(self):
        return self.row_state

    def _is_last(self, number):
        return self._index.get(number) == len(self.row_numbers) - 1

    def skip_count(self, number):
        """Number of fields that would be lost by crossing `number`."""
        return self._index[number] - self.position - 1

    def can_cross(self, number):
        if self.is_locked or number not in self._index:
            return False
        if self._index[number] <= self.position:
            return False
        if self._is_last(number) and self.crosses < MIN_CROSSES_TO_LOCK:
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
        return (self.position >= len(self.row_numbers) - 2
                and self.crosses < MIN_CROSSES_TO_LOCK)

    def score(self):
        return self.crosses * (self.crosses + 1) // 2

    def _is_row_full(self):
        return self.is_locked
