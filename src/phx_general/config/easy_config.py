import typing
import typeguard
import yaml
from enum import Enum

from phx_general.file import check_file
from phx_general.type import PathType

class EasyType(Enum):
    """
    Allowed types for yaml config
    """
    BOOL = bool
    STRING = str
    LIST = list
    INT = int
    FLOAT = float


@typeguard.typechecked
class EasyVariable:
    def __init__(self, type: EasyType = None, can_be_none: bool = False):
        self.type = type
        self.can_be_none = can_be_none


class EasyOptVariable(EasyVariable):
    def __init__(self, type: EasyType = None, default_value: typing.Any = None, can_be_none: bool = False):
        super().__init__(type, can_be_none)
        self.default_value = default_value

    def __post_init__(self):
        # check if default value has correct type
        if self.type and self.default_value:
            assert isinstance(self.default_value, self.type.value), \
                f"default_value has type: {type(self.default_value)} Expected type: {self.type}"


class EasyCfg:
    def __init__(self, config_path: PathType):
        self._config_path = config_path
        self._load_config()

    def _load_config(self):
        attribute_names = [attr for attr in dir(self) if not callable(getattr(self, attr)) and
                           not attr.startswith("__") and not attr.startswith("_")]
        cfg_variables = self._load_yaml()
        for attribute_name in attribute_names:
            attribute = getattr(self, attribute_name)
            if isinstance(attribute, EasyOptVariable):
                if attribute_name in cfg_variables:
                    self._set_attr(attribute_name, attribute.type, cfg_variables[attribute_name], attribute.can_be_none)
                else:
                    self._set_attr(attribute_name, attribute.type, attribute.default_value, attribute.can_be_none)
            elif isinstance(attribute, EasyVariable):
                if attribute_name not in cfg_variables:
                    raise ValueError(f"Variable '{attribute_name}' is missing in config '{self._config_path}'")
                self._set_attr(attribute_name, attribute.type, cfg_variables[attribute_name], attribute.can_be_none)
            else:
                raise ValueError(f"Attribute '{attribute_name}' must be instance of EasyVariable.")

    def _load_yaml(self):
        check_file(self._config_path)
        with open(self._config_path) as fin:
            return yaml.safe_load(fin)

    def _set_attr(self, attribute_name: str, attribute_type: EasyType, value, can_be_none: bool):
        if attribute_type:
            try:
                if value is None and not can_be_none:
                    raise ValueError()
                elif value is None and can_be_none:
                    value = None
                elif not isinstance(value, attribute_type.value):
                    value = attribute_type.value(value)
            except (ValueError, TypeError):
                raise TypeError(f"Variable '{attribute_name}' should be type '{attribute_type.value}', "
                                f"but is '{type(value)}' in config '{self._config_path}'")
        setattr(self, attribute_name, value)
