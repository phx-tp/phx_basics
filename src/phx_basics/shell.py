import logging
import os
import subprocess
import shlex
from pathlib import Path

from phx_basics.file import check_file, check_dir
from phx_basics.logging_tools import logging_format

_logger = logging.getLogger(__name__)


class LogFilter(logging.Filter):
    """
    Logging filter that filter only levels defined in constructor
    """
    def __init__(self, levels):
        """
        Create logging filter with defined levels to pass
        :param levels: (integer or set or list of integers) logging levels
        """
        log_levels = {0, 10, 20, 30, 40, 50}
        super().__init__()
        try:
            if type(levels) == int:
                if levels in log_levels:
                    self.levels = {levels}
                else:
                    raise TypeError()
            elif type(levels) in [list, set]:
                if not set(levels).issubset(log_levels):
                    raise TypeError()
                self.levels = levels
            else:
                raise TypeError()
        except TypeError:
            raise TypeError(
                "Argument 'levels' have to be integer or set or list of these integers: 0, 10, 20, 30, 40, 50")

    def filter(self, record):
        """
        Mandatory function for logging filtering
        :param record: mandatory input for logging filtering
        :return: boolean to pass
        """
        return record.levelno in self.levels


class ShellLogger(logging.Logger):
    """
    Logger designed for shell function
    """
    def __init__(self, use_logging):
        super(ShellLogger, self).__init__(logging.Logger("ShellLogger"))
        self.setLevel(logging.DEBUG)
        self.propagate = False
        self.use_logging = use_logging

    def addFilteredHandler(self, log, levels):
        """
        Add handler that pass through only defined levels
        :param log: path to file for output, can be None for creating StreamHandler
        :param levels: (integer or set or list of integers) logging levels to be passed into handler
        :return:
        """
        if log is None:
            h = logging.StreamHandler()
        else:
            if os.path.isfile(log):
                os.remove(log)
            h = logging.FileHandler(log)
        h.setLevel(logging.DEBUG)
        h.addFilter(LogFilter(levels))
        if self.use_logging:
            h.setFormatter(logging.Formatter(logging_format()))
        else:
            h.setFormatter(logging.Formatter('%(message)s'))
        self.addHandler(h)


def shell(cmd, cwd=None, input_string=None, stdout=None, stderr=None, use_logging=False, debug=False, check=True,
          env=None, shell=False, truncate_last_newline=True, ext_logger=None):
    """
    Run shell command in subshell
    :param cmd: (list) command to run
    :param cwd: path to change current directory
    :param input_string: input to pipe to process
    :param stdout: path to file for stdout, can be None for writing stdout to console
    :param stderr: path to file for stderr (can be same as stdout), can be None for writing stderr to console
    :param use_logging: use logging for output
    :param check: raise exception when return code from subprocess is not 0
    :param truncate_last_newline: delete last newline in stdout file if present
    :param ext_logger: Use external logger instead of the local.
    :return: Return output of the subprocess.run
    """
    def check_log(log):
        """
        Check if it is possible to write to log file, if not raise exception and write reason.
        :param log: path to log file
        :return:
        """
        if log is not None:
            if os.path.isfile(log):
                check_file(log)
            else:
                check_dir(os.path.dirname(os.path.realpath(log)))

    def check_command(command):
        """
        Check if command contains character '>' - if so raise exception
        :param command:
        :return:
        """
        if ">" in command:
            raise ValueError("Command contains forbidden string '>'. "
                             "Use parameter 'stdout' and/or 'stderr' instead.")

    def truncate(file_path):
        linesep_len = len(os.linesep)
        if file_path and os.path.exists(file_path) and Path(file_path).stat().st_size >= linesep_len:
            if file_path:
                with open(file_path, "rb+") as file:
                    file.seek(-linesep_len, 2)
                    if file.read(1) == os.linesep.encode("utf-8"):
                        file.seek(-linesep_len, 2)
                        file.truncate()

    assert type(cmd) == list
    check_command(cmd)
    assert input_string is None or type(input_string) == str
    assert type(use_logging) == bool
    assert type(check) == bool
    if cwd is not None:
        check_dir(cwd)
    if ext_logger is not None:
        logger = ext_logger
    else:
        check_log(stdout)
        check_log(stderr)
        _logger.debug(f"Running command: '{' '.join(cmd)}'")
        logger = ShellLogger(use_logging)
        if stdout == stderr and stdout is not None:
            logger.addFilteredHandler(stdout, [logging.DEBUG if debug else logging.INFO, logging.ERROR])
        else:
            logger.addFilteredHandler(stdout, logging.DEBUG if debug else logging.INFO)
            logger.addFilteredHandler(stderr, logging.ERROR)
    try:
        result = subprocess.run(cmd, input=input_string, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, check=check, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        logging.error("\n".join(("Stderr in subprocess:", "STDOUT:", e.stdout, "STDERR:", e.stderr)))
        if stderr is not None:
            logger.error(e.stderr)
        raise e
    if result.stdout != "":
        logger.info(result.stdout)
    if result.stderr != "":
        logger.error(result.stderr)
    if truncate_last_newline:
        truncate(stdout)
        truncate(stderr)
    return result


def shell_source(script, update_env=False):
    """
    A function to emulate the action of 'source env.sh' respectively '. env.sh' in shell.
    :param script: Path to an environment setup script with variables, compatible with shell (no tricky loops etc.)
    :param update_env: If True, it will set or update environment variables in os.environ .
    :return: Return dictionary with variables extracted from the script
    """
    pipe = subprocess.Popen(". %s && env -0" % script, stdout=subprocess.PIPE, shell=True)
    output = pipe.communicate()[0].decode('utf-8')
    output = output[:-1]  # fix for index out for range in 'env[ line[0] ] = line[1]'

    env = {}
    # split using null char
    for line in output.split('\x00'):
        line = line.split('=', 1)
        if len(line) != 2:
            continue
        env[line[0]] = line[1]

    if update_env:
        os.environ.update(env)
    return env


def bash_source(script):
    """
    This function runs a bash command to `source script` and get the environment variables.
    Use this function instead of `shell_source` when the environment script use loops and
    other POSIX shell incompatible syntax.
    It will automatically set or update environment variables in os.environ .
    :param script: Path to an environment setup script with variables, compatible with bash.
    :return: Return dictionary with variables extracted from the script
    """
    command = shlex.split(f"bash -c 'source {script} && env'")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE)
    for line in proc.stdout:
        key, _, value = line.decode().partition("=")  # line.decode().strip().partition("=")
        os.environ[key] = value
    proc.communicate()
    env_vars = dict(os.environ)
    return env_vars
