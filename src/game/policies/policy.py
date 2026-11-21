# defines the policy which should be followed to play the game

class Policy():

    def __init__(self):
        pass

    def act(self, dices, rows):
        dices_values = {}
        for dice in dices:
            # print(dice._get_repr())
            dices_values = dices_values | dice._get_repr()
        sum_of_whites = dices_values["W1"] + dices_values["W2"]
        sum_of_reds = (dices_values["W1"] + dices_values["R1"], dices_values["W2"] + dices_values["R1"])
        sum_of_greens = (dices_values["W1"] + dices_values["G1"], dices_values["W2"] + dices_values["G1"])
        sum_of_blues = (dices_values["W1"] + dices_values["B1"], dices_values["W2"] + dices_values["B1"])
        sum_of_yellows = (dices_values["W1"] + dices_values["Y1"], dices_values["W2"] + dices_values["Y1"])
        print(f"w: {sum_of_whites}, reds: {sum_of_reds}, blues: {sum_of_blues}, greens: {sum_of_greens}, yellows: {sum_of_yellows}")

        rows_values = {}
        for row in rows:
                rows_values[row.color] = row
                # print(row._get_repr())
        print(rows_values)


        # 1. check if white sum can be placed
        # min diff for a color

        # min_diffs = {Color:[Wert, Diff, w/c/wc]}
        for k,v in rows_values.items():
            # print(k, v)
            diff = v.largest_crossed_number - sum_of_whites
            print(f"diff {v.color}: {diff}")

        # 2. check if color sum can be placed

        # 3. if nothing, check a box
        pass