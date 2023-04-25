import logging
import os
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)


class SkipWithBlock(Exception):
    pass


class SimpleStage:
    """
    Solution derived from https://stackoverflow.com/questions/12594148/skipping-execution-of-with-block
    SimpleStage is context manager that should be used with 'with' statement.
    Stage will check if 'done' file exists and if so stage is skipped.
    If stage is processed the 'done' file is created in the end of stage.
    Cons: This solution uses sys._getframe() which can be unstable
    """
    directory = None

    def __init__(self, stage_name, force=False):
        self.skip = not force
        self._stage_name = stage_name.replace("/", "_")
        if not self.directory:
            raise ValueError(f"Before usage of {self.__name__}, define 'directory' class variable: "
                             f"{self.__name__}.{self.directory.__name__}")

    def __enter__(self):
        if self.skip and self._get_stage_done_file_path().is_file():
            _logger.warning(f"Skipping stage '{self._stage_name}'")
            sys.settrace(lambda *args, **keys: None)
            frame = sys._getframe(1)
            frame.f_trace = self.trace
        else:
            _logger.info(f"Running stage '{self._stage_name}'")

    def trace(self, frame, event, arg):
        raise SkipWithBlock()

    def _get_stage_done_file_path(self):
        return Path(self.directory) / f".stage_{self._stage_name}_done"

    def __exit__(self, err_type, value, traceback):
        if err_type is None:
            os.makedirs(self.directory, exist_ok=True)
            self._get_stage_done_file_path().touch()
            return  # No exception
        if issubclass(err_type, SkipWithBlock):
            return True  # Suppress special SkipWithBlock exception
