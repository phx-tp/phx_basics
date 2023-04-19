import multiprocessing

from typeguard import typechecked


@typechecked
def check_cores(cores: int):
    assert cores >= 0, "Parameter 'cores' must be higher or equal to 0"
    assert cores <= multiprocessing.cpu_count(), \
        f"Parameter 'cores' must be less or equal to actual cpu cores ({multiprocessing.cpu_count()})"
    return cores
