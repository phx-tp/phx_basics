#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
General utilities for working with files, directories, filesystems
"""

import os
import shutil
import gzip
import re
from pathlib import Path
from typing import Iterable
from typeguard import typechecked
from phx_basics.dir import check_dir
from phx_basics.type import PathType


@typechecked
def check_file(filepath: PathType):
    if not Path(filepath).is_file():
        if Path(filepath).is_dir():
            raise FileExistsError(f"Path '{str(filepath)}' is directory, not file")
        else:
            raise FileNotFoundError(f"File '{str(filepath)}' doesn't exist")


@typechecked
def file2list(file_path: PathType, strip=True):
    """
    Source file to list
    :param strip: (bool) if to strip every line
    :param file_path: file to source
    :return: list of rows
    """
    check_file(file_path)
    with open(file_path) as fin:
        if strip:
            lines = list()
            for line in fin:
                lines.append(line.strip())
            return lines
        else:
            return fin.readlines()


@typechecked
def file2set(file_path: PathType):
    """
    load set from file where every striped line from file added
    :param file_path: path to input file
    :return: set of striped lines
    """
    check_file(file_path)
    l_set = set()
    with open(file_path) as l_fin:
        for l_l in l_fin:
            l_set.add(l_l.strip())
    return l_set


def list2file(lines: Iterable, file_path: PathType, add_sep=True):
    """
    Write list to file one row by row
    :param add_sep: (bool) add line separator to the end of every line
    :param lines: input list
    :param file_path: output file
    :return:
    """
    check_dir(Path(file_path).parent)
    with open(file_path, "w") as fout:
        if add_sep:
            for line in lines:
                fout.write(line+os.linesep)
        else:
            fout.writelines(lines)


def file2dict(file_path: PathType, sep="\t"):
    """
    source dictionary from file where first column is key and second is value
    :param file_path: path to input file
    :param sep: separator of columns (default is tabulator)
    :return: dictionary
    """
    check_file(file_path)
    out_dict = dict()
    with open(file_path) as fin:
        for n, l in enumerate(fin):
            columns = l.split(sep)
            if len(columns) != 2:
                raise ValueError(f"Making dict from file '{file_path}', but there is {len(columns)} "
                                 f"columns instead of 2 on row  {n}: '{l}'")
            out_dict[columns[0].strip()] = columns[1].strip()
    return out_dict


def file2iter(file_path: PathType, strip=True):
    """
    Source file to iterator
    :param strip: (bool) if to strip every line
    :param file_path: file to source
    :return: iterator per line
    """
    check_file(file_path)
    with open(file_path) as fin:
        for line in fin:
            if strip:
                yield line.strip()
            else:
                yield line


def safe_copy(src: PathType, dst: PathType):
    """
    copy file even if dst exists and even dst is a symlink
    """
    if os.path.exists(dst):
        if os.path.islink(dst):
            os.unlink(dst)
        else:
            os.remove(dst)
    shutil.copy(src, dst)


def file2id_dict(file: PathType, strip: bool = True, delimiter: str = "\t"):
    """
    Source file and save to Dict[str, List[tuple[str]]], when key is first column. Keys can be repeated but must be
    sorted (). This format is usually used in KALDI. Value is List of rest of columns saved as tuple.
    """
    check_file(file)
    id_dict = dict()
    prev_key = None
    value_list = None
    for line in file2iter(file, strip=strip):
        columns = line.strip().split(delimiter)
        assert len(columns) >= 2, columns
        key = columns[0]
        value = columns[1:]
        if key != prev_key:
            value_list = list()
            id_dict[key] = value_list
            prev_key = key
        value_list.append(value)
    return id_dict


@typechecked
class GzipOpener:
    @staticmethod
    def open_file(input_path: str):
        _open = (lambda x: open(x, "r")) if not re.fullmatch("^.*\\.gz$", input_path) else lambda x: gzip.open(x, "rt")
        return _open(input_path)
