import random


class Dice():

    def __init__(self, color, no_sides=6):
        self.color = color
        self.no_sides = no_sides
        self.face_value = None

    def _get_repr(self):
        return {self.color: self.face_value}

    def throw(self):
        self.face_value = random.randint(1, self.no_sides)
