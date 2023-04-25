import multiprocessing

from typeguard import typechecked


@typechecked
def check_cores(cores: int):
    max_local_cores = multiprocessing.cpu_count()
    assert cores >= 0, "Parameter 'cores' must be higher or equal to 0"
    assert cores <= max_local_cores, \
        f"Parameter 'cores' must be less or equal to actual cpu cores ({max_local_cores})"
    if cores == 0:
        cores = max_local_cores
    return cores
