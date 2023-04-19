#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
General utilities for working with files, directories, filesystems
"""
from pathlib import Path
from typing import Union, Iterable

import os
import shutil
import logging
import zipfile
from typeguard import typechecked


@typechecked
def check_file(file_path: Union[str, Path]):
    assert Path(file_path).is_file(), f"'{file_path}' is not a file"


@typechecked
def check_dir(dir_path: Union[str, Path]):
    assert Path(dir_path).is_dir(), f"'{dir_path}' is not a directory"


@typechecked
def mkpdirp(file_path: Union[str, Path]):
    """
    Create parent directory of file (can be dir too), no error if existing, make parent directories as needed
    :param file_path: file path
    :return:
    """
    check_file(file_path)
    directory = os.path.dirname(file_path)
    # don't throw error when path is relative and parent directory is current directory
    if directory == "":
        return
    os.makedirs(directory, exist_ok=True)


@typechecked
def file2list(file_path: Union[str, Path], strip=True):
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
def file2set(file_path: Union[str, Path]):
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


def list2file(lines: Iterable, file_path: Union[str, Path], add_sep=True):
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


def file2dict(file_path: Union[str, Path], sep="\t"):
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
                raise ValueError(f"Making dict from file '{file_path}', but there is {len(columns)} columns instead of 2 on row  {n}: '{l}'")
            out_dict[columns[0].strip()] = columns[1].strip()
    return out_dict


def file2iter(file_path: Union[str, Path], strip=True):
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


def zip_folder(folder_path: Union[str, Path], output_path: Union[str, Path]):
    """
    Zip the contents of an entire folder (without that folder included
    in the archive). Empty subfolders will be included in the archive
    as well.
    :param folder_path: path to input folder
    :param output_path: path to output file
    :return: 
    """
    check_dir(folder_path)
    # Retrieve the paths of the folder contents.
    contents = os.walk(folder_path)
    try:
        zip_file = zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED)
        for root, folders, files in contents:
            # Include all subfolders, including empty ones.
            for folder_name in folders:
                absolute_path = os.path.join(root, folder_name)
                relative_path = absolute_path.replace(folder_path, '')
                logging.debug("Adding '%s' to archive." % relative_path)
                zip_file.write(absolute_path, relative_path)
            for file_name in files:
                absolute_path = os.path.join(root, file_name)
                relative_path = absolute_path.replace(folder_path, '')
                logging.debug("Adding '%s' to archive." % relative_path)
                zip_file.write(absolute_path, relative_path)
        logging.debug("'%s' created successfully." % output_path)
        zip_file.close()
    except IOError as message:
        raise IOError(message)
    except OSError as message:
        raise OSError(message)
    except zipfile.BadZipfile as message:
        raise Exception(message)


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


def safe_copy(src: Union[str, Path], dst: Union[str, Path]):
    """
    copy file even if dst exists and even dst is a symlink
    """
    if os.path.exists(dst):
        if os.path.islink(dst):
            os.unlink(dst)
        else:
            os.remove(dst)
    shutil.copy(src, dst)


def file2id_dict(file: Union[str, Path], strip: bool = True, delimiter: str = "\t"):
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
