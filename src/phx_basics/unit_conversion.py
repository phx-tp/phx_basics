from typeguard import typechecked


@typechecked
def hms2sec(string: str):
    def raise_verror():
        raise ValueError(
            "Bad format! Expected: 'HHh MMm SSs', where H means hours, M means minutes and S means seconds.")
    sl = string.split()
    if sl.__len__() != 3:
        raise_verror()
    if sl[0][-1] != "h":
        raise_verror()
    if sl[1][-1] != "m":
        raise_verror()
    if sl[2][-1] != "s":
        raise_verror()
    hours = int(sl[0][:-1])
    mins = int(sl[1][:-1])
    secs = int(sl[2][:-1])
    return 60 * 60 * hours + 60 * mins + secs


@typechecked
def sec2hms(seconds: float):
    secs = seconds % 60
    mins = int((seconds % 3600) / 60)
    hours = int(seconds / 3600)
    return "%02dh %02dm %02ds" % (hours, mins, secs)
