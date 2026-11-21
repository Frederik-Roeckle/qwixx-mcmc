

class Row():
    is_complete = False

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

    def _get_repr(self):
        return self.row_state


    def _is_row_full(self):
        # if last element of the dict has a 1 in its state, the row is complete
        # print(self.row_state.values())
        if list(self.row_state.values())[-1] == 1:
            self.is_complete = True
        return self.is_complete

    def _write_number(self, number):
        self.row_state[number] = 1
        self.largest_crossed_number = number
        return 0
