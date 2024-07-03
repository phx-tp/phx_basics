import argparse
import multiprocessing

from typeguard import typechecked


@typechecked
def check_cores(cores: int, autocorrect: bool = True):
    max_local_cores = multiprocessing.cpu_count()
    assert cores >= 0, "Parameter 'cores' must be higher or equal to 0"
    if autocorrect:
        if cores > max_local_cores:
            cores = max_local_cores
    else:
        assert cores <= max_local_cores, \
            f"Parameter 'cores' must be less or equal to actual cpu cores ({max_local_cores})"
    if cores == 0:
        cores = max_local_cores
    return cores


class ArgparseCoreType(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            values = int(values)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Parameter '{option_string}' must be an integer")
        try:
            check_cores(values, autocorrect=True)
        except AssertionError as e:
            raise argparse.ArgumentTypeError(str(e).replace("'cores'", option_string))
        setattr(namespace, self.dest, int(values))
