import argparse
import logging

from typeguard import typechecked

from phx_basics.logging_tools import logging_format


@typechecked
class ArgParser:
    """
    Create parser with debug and warning options and set logging. Parser can be modified as argparse.ArgumentParser via
    'self.parser'.
    Most commonly used "add_argument" method can be used directly and will proxy args and kwargs to 'self.parser'.
    """
    def __init__(self, description: str = ""):
        self.parser = self._default_parser(description)

    @staticmethod
    def _default_parser(description: str = "") -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        logging_level = parser.add_mutually_exclusive_group()
        logging_level.add_argument("--debug", action="store_true", help="Print debug logging")
        logging_level.add_argument("--warning", action="store_true", help="Print only warning logging")
        parser.add_argument("--log", help="Log all into file", metavar="LOGFILE")
        return parser

    def add_argument(self, *args, **kwargs):
        """ Proxy to argparse's add_argument method """
        self.parser.add_argument(*args, **kwargs)

    def __call__(self):
        args = self.parser.parse_args()
        logging.basicConfig(format=logging_format(),
                            level=logging.DEBUG if args.debug else (logging.WARNING if args.warning else logging.INFO),
                            filename=args.log,
                            filemode="w")
        return args
