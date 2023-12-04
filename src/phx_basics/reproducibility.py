"""
Utilities to make a executed python program/process replicable
used e.g. during ML prototyping
"""
import sys
import os
import shutil
import tarfile
import logging
import codecs
from datetime import datetime
from pathlib import Path
from phx_basics.dir import check_dir

AUTOBACKUP_PREFIX = "autobackup"

_logger = logging.getLogger(__name__)


def get_datetime_suffix():
    return datetime.now().strftime('%Y-%m-%d--%H-%M-%S--%f')[:-3]


def get_backups(dirname):
    """
    Returns all the files/directories starting with AUTOBACKUP_PREFIX in 'dirname' directory
    """
    check_dir(dirname)

    backups = []
    # backup the former backups that we rely on
    for item in os.listdir(dirname):
        if AUTOBACKUP_PREFIX in item:
            backups.append(Path(dirname) / item)

    return backups


def make_backup(backup_output_dir,
                name=None,
                files_and_dirs=None,
                repository_root=None,
                compress_codebase=True,
                ):
    """
    Backup source code, parameters and files for a python program - e.g. machine learning experiment

    Backup:
     - commandline parameters of python program that was run
     - codebase == all files from repository root
         - if no repository root is specified, we search for nearest git repository in CWD parents
         - "core" files are removed
         - all files in the repository should be less than 50 MB, otherwise auto-backup gets very slow
    - any other files/directories specified in dictionary 'files_and_dirs', these are files needed by the program
      to execute correctly or any additional info about data etc. stored in files, no size checks etc. are carried on
      -> be careful what to put here

    :param backup_output_dir:      Path to directory where backup will be stored, the function will create subfolder
                                   with name <AUTOBACKUP_PREFIX>_<name - if specified>_<datetime> where all the backup
                                   gets stored
    :param name                    Optional name to be incorporated into backup name
    :param files_and_dirs:         Dictionary where keys are paths to files and directories which should be backed up
                                   Values are optional new names for the files/dirs or None/'' to use original name
                                   e.g.  {  '/sth/path.txt': 'backup_of_sth.txt', '/sth/dir': ''} will result into
                                        backup_output_dir/<autoname>/{backup_of_sth.txt, dir} being in backup
    :param find_backups_in:        List of directories where to look for 'AUTOBACKUP_PREFIX*' files/directories
    :param repository_root:
    :param compress_codebase:      Whether codebase should be compressed (stored as tar.gz)
    :return:                       Name of the repository with backup
    """
    # compose the name of output directory
    suffix = get_datetime_suffix()
    if name:
        suffix = f"{suffix}_{name}"
    out_path = Path(backup_output_dir) / f"{AUTOBACKUP_PREFIX}_{suffix}"
    os.makedirs(out_path)

    backup_commandline_arguments(out_path)
    backup_codebase(out_path, repository_root=repository_root, compress=compress_codebase)

    # backup additional files and directories
    if files_and_dirs:
        for item, new_name in files_and_dirs.items():
            assert Path(item).exists(), item
            backup_file_or_dir(out_path, item, name=new_name, auto_naming=False)

    return out_path


def backup_commandline_arguments(backup_output_dir):
    """

    :param backup_output_dir:
    :param dttm: Optional string describing datetime or any other
    :return:
    """
    out_path = Path(backup_output_dir) / f'cmdline_args.txt'
    assert not os.path.exists(out_path)
    with codecs.open(out_path, mode='wb', encoding='utf-8') as fd:
        print(sys.argv, file=fd)

    return out_path


def backup_file_or_dir(out_dir, filename_or_dirname, name="", auto_naming=True):
    """
    Adds file/directory to backup
    :param out_dir:              Where to copy file/dir
    :param filename_or_dirname:  file/dir  to be backed up
    :param name:                 optionally change the name of file/dir to this value
    :param auto_naming:          optionally prepend the name of file with AUTOBACKUP_PREFIX and suffix with DATETIME string
    :return:                     path to file/dir in backup directory
    """
    if name:
        backup_name = name  # rename file/dir
    else:
        backup_name = os.path.basename(filename_or_dirname)   # leave the file/dir's basename

    out_path = Path(out_dir) / backup_name
    if not auto_naming:
        out_path = Path(out_dir) / f"{AUTOBACKUP_PREFIX}_{get_datetime_suffix()}__{backup_name}"

    if Path(filename_or_dirname).is_dir():
        shutil.copytree(filename_or_dirname, out_path)
    else:
        shutil.copy(filename_or_dirname, out_path)

    return out_path


def backup_codebase(backup_output_dir, repository_root=None, compress=True):
    """
    Backups all the source code from given reposiory_root if
    :param backup_output_dir:
    :param repository_root:
    :param compress: whether codebase should be tarred
    :return:                          path to .tgz file in the backup directory
    """

    # find repository root
    if not repository_root:
        "Find repository root from the cwd path's parents"
        for path in Path("./").resolve().parents:
            # Check whether "path/.git" exists and is a directory
            git_dir = path / ".git"
            if git_dir.is_dir():
                repository_root = path
                break
    else:
        repository_root = Path(repository_root)

    git_dir = repository_root / ".git"
    assert git_dir.is_dir(), git_dir

    # remove core files which might be in a directory after some crashes of various binaries and might be big
    for root, dirs, files in os.walk(repository_root):
        for f in files:
            if f == "core":
                _logger.warning(f"Removing 'core' file in directory: {root}")
                os.remove(f)

    # backup source code
    if compress:
        out_path = Path(backup_output_dir) / f"src.tgz"
        assert not os.path.exists(out_path)
        with tarfile.open(out_path, "w:gz") as tar_handle:
            for root, dirs, files in os.walk(repository_root):
                for f in files:
                    f = os.path.join(root, f)
                    assert os.stat(f).st_size <  5e+7, os.stat(f).st_size  # don't allow files bigger than 50 MB in the repo
                    tar_handle.add(f)
    else:
        out_path = Path(backup_output_dir) / f"src"
        assert not os.path.exists(out_path)
        for root, dirs, files in os.walk(repository_root):
            for f in files:
                f = os.path.join(root, f)
                assert os.stat(f).st_size <  5e+7, os.stat(f).st_size  # don't allow files bigger than 50 MB in the repo
        shutil.copytree(repository_root, out_path)

    return out_path
