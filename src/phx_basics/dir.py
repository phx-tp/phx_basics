import logging
import os
import zipfile
from pathlib import Path
from typeguard import typechecked
from phx_basics.type import PathType


@typechecked
def check_dir(filepath: PathType):
    if not Path(filepath).is_dir():
        if Path(filepath).is_file():
            raise NotADirectoryError(f"Path '{str(filepath)}' is file, not directory")
        else:
            raise NotADirectoryError(f"Directory '{str(filepath)}' doesn't exist")


@typechecked
def mkpdirp(file_path: PathType):
    """
    Create parent directory of file (can be dir too), no error if existing, make parent directories as needed
    :param file_path: file path
    :return:
    """
    directory = os.path.dirname(file_path)
    # don't throw error when path is relative and parent directory is current directory
    if directory == "":
        return
    os.makedirs(directory, exist_ok=True)


def zip_folder(folder_path: PathType, output_path: PathType):
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


