#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import argparse
import logging
import os
import mmap
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Union

import typeguard

from phx_basics.cpu_utils import check_cores
from phx_basics.file import file2list, file2iter, list2file
from phx_basics.shell import shell
from phx_basics.type import PathType


def mapcount(filename):
    """
    count rows of file in efficient way
    :param filename: path to input file
    :return: number of lines
    """
    f = open(filename, "r+")
    buf = mmap.mmap(f.fileno(), 0)
    lines = 0
    readline = buf.readline
    while readline():
        lines += 1
    return lines


@typeguard.typechecked
class SGE:
    _error_file_suffix = ".error"
    _default_conda_name = "base"

    def __init__(self):
        pass

    @classmethod
    def create_run_file_lines(cls,
                              command: str,
                              memory_alloc: Union[float, int],
                              output_file: PathType,
                              queue_name: str = "all.q",
                              sync: bool = True,
                              conda_env_name: Union[str, None] = None,
                              gpus: int = 0,
                              pe_name: str = "smp",
                              cpus: int = 1):
        run_file_lines = list()

        run_file_lines.append("#$ -S /bin/bash")
        resources = f"#$ -l ram_free={memory_alloc}G,mem_free={memory_alloc}G"
        if gpus > 0:
            resources += f",gpu={gpus}"
        run_file_lines.append(resources)
        run_file_lines.append("#$ -V")
        if sync:
            run_file_lines.append("#$ -sync yes")
        output_file = Path(output_file).absolute()
        run_file_lines.append(f"#$ -N {output_file.name}")  # job name
        run_file_lines.append(f"#$ -o {output_file}.$JOB_ID")  # output file
        run_file_lines.append(f"#$ -e {str(output_file)}.$JOB_ID{cls._error_file_suffix}")  # error file
        cpus = check_cores(cpus)
        if cpus > 0:
            run_file_lines.append(f"#$ -pe {pe_name} {cpus}")  # parallel environment
        run_file_lines.append("#$ -q {}".format(queue_name))  # queue name
        if conda_env_name:
            with tempfile.NamedTemporaryFile() as tmp:
                # shell(["which", "conda"], check=True, stdout=tmp.name)
                # conda = file2list(tmp.name)
                # assert (len(conda) == 1)
                # conda = conda[0].strip().replace("condabin/conda", "bin/conda")
                run_file_lines.append("__sge_conda_setup=\"$('conda' 'shell.bash' 'hook' 2> /dev/null)\"")
                run_file_lines.append("eval \"$__sge_conda_setup\"")
                run_file_lines.append(f"conda activate {conda_env_name}")
        run_file_lines.append(command)
        run_file_lines.append("ERROR_CODE=$?")
        run_file_lines.append("exit $ERROR_CODE")
        return run_file_lines



def sge_manage_task(commands_file_path, name=None, output_file=None, error_file=None, memory_alloc=4,
                    dont_export_env_variables=False, sync=True, queue="all.q", pe_slots=0, pe_name="smp",
                    project_name=None, gpu=0, conda_environment=None):
    """
    Run commands from input file in SGE by shell script; If processing fail CalledProcessError is called with printing
    of stdout and stderr
    :param project_name: name of project for '-P' parameter
    :param commands_file_path: path to input file with commands
    :param name: name of job
    :param output_file: path to output file from sge (log - stdout)
    :param error_file: path to error file from sge (stderr)
    :param memory_alloc: integer how many gigabytes of memory to lock at host
    :param dont_export_env_variables: boolean to export all envirormental variables
    :param sync: boolean to wait until sge task is done
    :param queue: name of queue to use
    :param pe_slots: number of slots for paralel envirorment
    :param pe_name: name of paralel envirorment - not used if pe_slot is None
    :param conda_environment: path to conda binary, the conda initialization will be prepended before running the commands
    :return: 
    """
    commands_file_path = os.path.abspath(commands_file_path)
    if output_file:
        output_file = os.path.abspath(output_file)

    run_file_lines.append("".join((" $(sed -n ${SGE_TASK_ID}p ", commands_file_path, ")")))
    run_file_lines.append("ERROR_CODE=$?")
    run_file_lines.append("exit $ERROR_CODE")
    with open(commands_file_path+".run.sh", "w") as fout:
        fout.write("\n".join(run_file_lines))
    nj = mapcount(commands_file_path)
    cmd = ["qsub", "-t", "1:{}".format(str(nj)), commands_file_path+".run.sh"]
    logging.debug("Runing SGE job '{}'".format(" ".join(cmd)))
    try:
        shell(cmd, check=True)
    except FileNotFoundError as e:
        if e.args[1] == "No such file or directory: 'qsub'":
            raise SystemError("System isn't in SGE. Run commands from '{}' without SGE.".format(commands_file_path))
        else:
            raise e


def gpu_manage_task(commands_file_path, name=None, output_file=None, error_file=None, memory_alloc=4,
                    dont_export_env_variables=False, sync=True, queue="all.q", pe_slots=0, pe_name="smp",
                    project_name=None, gpu=0, sleep_period=20, sleep_cycle=20,
                    free_gpu_script=None):
    if not free_gpu_script:
        free_gpu_script = str(Path(__file__).absolute().parent / "free_gpus.py")
    tmp_dir = Path(commands_file_path).parent / "_jobs"
    os.makedirs(tmp_dir)
    new_command_list_path = commands_file_path + "_new"
    new_command_list = list()
    sleep = (sleep_cycle - 1) * sleep_period
    for i, command in enumerate(file2iter(commands_file_path)):
        script_path = tmp_dir / f"{i}.sh"
        new_command_list.append(f"bash {script_path}")
        new_script = [f"export CUDA_VISIBLE_DEVICES=$({sys.executable} {free_gpu_script})",
                      # "echo 'free gpu:' $CUDA_VISIBLE_DEVICES $HOSTNAME", # for debuging only
                      command]
        if sleep_period and sleep_period > 0:
            sleep += sleep_period
            if sleep_cycle:
                sleep %= (sleep_cycle * sleep_period)
            new_script = [f"sleep {sleep}"] + new_script
        list2file(new_script, script_path)
    list2file(new_command_list, new_command_list_path)
    sge_manage_task(new_command_list_path,
                    name=name,
                    output_file=output_file,
                    error_file=error_file,
                    memory_alloc=memory_alloc,
                    dont_export_env_variables=dont_export_env_variables,
                    sync=sync,
                    queue=queue,
                    pe_slots=pe_slots,
                    pe_name=pe_name,
                    project_name=project_name,
                    gpu=gpu)


def main():
    description = "This script is intended to run parallel jobs in SGE cluster by defining file with commands"
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--dont_export_env_variables", help="Do not import all environment variables to SGE",
                        action="store_true", default=False)
    parser.add_argument("-N", "--name", help="name of task in SGE", type=str, default=None)
    parser.add_argument("-o", "--output_file", help="path to file for standard output", type=str, default=None)
    parser.add_argument("-e", "--error_file", help="path to file for standard error", type=str, default=None)
    parser.add_argument("-s", "--sync", help="causes qsub to not wait for the job to complete before exiting",
                        action="store_false", default=True)
    parser.add_argument("-l", "--memory_alloc", help="locking RAM and HD memory on host per one job in gigabytes",
                        type=float, default=4)
    parser.add_argument("--pe", help="number of slots for parallel envirorment",
                        type=int, default=0)
    parser.add_argument("-c", "--conda_environment", help="Name of conda environment to get activated",
                        type=str, default=None)
    parser.add_argument("commands_file", help="path to input file")
    args = parser.parse_args()
    sge_manage_task(args.commands_file,
                        name=args.name,
                        output_file=args.output_file,
                        error_file=args.error_file,
                        memory_alloc=args.memory_alloc,
                        dont_export_env_variables=args.dont_export_env_variables,
                        sync=args.sync,
                        pe_slots=args.pe,
                        conda_environment=args.conda_environment)


if __name__ == "__main__":
    main()
