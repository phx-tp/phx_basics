
def kw_range(starting_kw, ending_kw, input_list):
    """
    get rows of list which starts with starting keyword and ending with ending keyword
    :param starting_kw: starting keyword
    :param ending_kw: ending keyword
    :param input_list: input list
    :return: range between keywords
    """
    output_list = list()
    write_switch = False
    for l in input_list:
        if l.rstrip() == starting_kw:
            write_switch = True
        if l.rstrip() == ending_kw:
            write_switch = False
        if write_switch:
            output_list.append(l)
    return output_list
