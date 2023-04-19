import os
import re
import tempfile

from typeguard import typechecked

from phx_general.file import file2list
from phx_general.shell import shell


def free_gpu():
    """
    Get id as string of first free GPU
    """
    return NvidiaSMIParser().get_free_gpu()


@typechecked
class NvidiaSMIParser:
    regex_gpu = re.compile("GPU (\\d)+:.*")
    regex_memory = re.compile(".*?(\\d+)MiB\\s+/\\s+\\d+MiB.*")

    def __init__(self):
        with tempfile.NamedTemporaryFile() as gpu_list:
            shell(["nvidia-smi", "-L"], stdout=gpu_list.name)
            self.gpu_list = self._parse_gpu_list(file2list(gpu_list.name))

    def get_free_gpus(self):
        """
        Get all free gpus on machine
        :return:
        """
        with tempfile.NamedTemporaryFile() as tmp:
            shell(["nvidia-smi"], stdout=tmp.name)
            indexes, rows_found = self._parse_free_gpu_indexes_from_nsvidia_smi(file2list(tmp.name))
        assert len(self.gpu_list) == rows_found
        if not indexes:
            raise NoFreeGpu(f"No free GPU available on '{os.uname()[1]}'")
        return [self.gpu_list[index] for index in indexes]

    def get_free_gpu(self):
        """
        Get one free GPU with the lowest ID
        """
        return self.get_free_gpus()[0]

    @classmethod
    def _parse_gpu_list(cls, nvidia_smi_gpu_list: list[str]):
        gpu_list = list()
        for line in nvidia_smi_gpu_list:
            match = cls.regex_gpu.match(line)
            if match:
                assert len(match.groups()) == 1
                gpu_list.append(match.groups()[0])
        if len(gpu_list) == 0:
            raise NoGpuFound(f"No GPU found on '{os.uname()[1]}'")
        return gpu_list

    @classmethod
    def _parse_free_gpu_indexes_from_nsvidia_smi(cls, nvidia_smi_output_list: list[str]):
        gpu_indexes = set()
        index = 0
        for line in nvidia_smi_output_list:
            used_memory = cls.regex_memory.findall(line)
            if used_memory:
                assert len(used_memory) == 1
                int_used_memory = int(used_memory[0])
                if int_used_memory <= 4:  # if memory is lower than 4 MB
                    gpu_indexes.add(index)
                index += 1
        return gpu_indexes, index


class NoGpuFound(ValueError):
    pass


class NoFreeGpu(ValueError):
    pass


def main():
    print(free_gpu())


if __name__ == '__main__':
    main()
