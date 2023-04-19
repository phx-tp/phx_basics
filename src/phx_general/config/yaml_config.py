from __future__ import annotations

import os
import typing
import logging
import yaml
from phx_general.file import check_file, list2file

from pydantic import dataclasses
from enum import Enum

_logger = logging.getLogger(__name__)


class YAMLConfigVariableType(Enum):
    """
    Allowed types for yaml config
    """
    BOOL = bool
    STRING = str
    LIST = list
    INT = int
    FLOAT = float

    @classmethod
    def get_values(cls):
        return list(map(lambda c: c.value, cls))

    @classmethod
    def to_plain_str(cls, value):
        assert value is None or isinstance(value, tuple(cls.get_values())), f"Unknown type to translate: {type(value)}"
        if isinstance(value, cls.LIST.value):
            return " ".join(value)
        elif value is None:
            return ""
        else:
            return str(value)


@dataclasses.dataclass(frozen=True)
class YAMLConfigVariable:
    name: str
    type: YAMLConfigVariableType = None


@dataclasses.dataclass(frozen=True)
class YAMLConfigOptionalVariable(YAMLConfigVariable):
    default_value: 'typing.Any' = None

    def __post_init__(self):
        # check if default value has correct type
        if self.type and self.default_value:
            assert isinstance(self.default_value, self.type.value), \
                f"default_value has type: {type(self.default_value)} Expected type: {self.type}"


class YAMLConfig:
    _dvc_all_variables_basename = "_VARIABLES_"

    def __init__(self, config_path, mandatory_variables=None, optional_variables=None):
        self.mandatory_variables = mandatory_variables
        self.optional_variables = optional_variables
        self._config_path = config_path
        self._variables = dict()
        self._load()

    @property
    def mandatory_variables(self):
        return self._mandatory_variables

    @mandatory_variables.setter
    def mandatory_variables(self, value):
        self._variables_setter("_mandatory_variables", value)
        for variable in self.mandatory_variables:
            assert not isinstance(variable, YAMLConfigOptionalVariable), "Mandatory variable can't be optional"

    @property
    def optional_variables(self):
        return self._optional_variables

    @optional_variables.setter
    def optional_variables(self, value):
        self._variables_setter("_optional_variables", value)

    def _variables_setter(self, variables_name, value: typing.Iterable[YAMLConfigVariable]):
        variables = None
        if value is not None:
            error_message = f"Parameter '{variables_name}' must be iterable of 'YAMLConfigVariable' or None, not "
            assert isinstance(value, typing.Iterable), error_message + f"{type(value)}"
            variables = dict()
            for iterable_item in value:
                assert isinstance(iterable_item,
                                  YAMLConfigVariable), error_message + f"iterable of {type(iterable_item)}"
                variables[iterable_item.name] = iterable_item
        setattr(self, variables_name, variables)

    def _load(self):
        check_file(self._config_path)
        with open(self._config_path) as fin:
            variables = yaml.safe_load(fin)
            self._load_variables(variables)

    def _load_variables(self, variables):
        """
        Check types of every variable and add optional variable if missing in config
        """
        assert isinstance(variables, dict), f"Yaml config yaml is expected to be defined as 'dict'"
        # mandatory variable has to be present in config
        missing = set(self.mandatory_variables.keys()).difference(variables)
        if missing:
            raise MissingVariablesError(f"Mandatory variables '{missing}' missing in config '{self._config_path}'")
        for variable_name, value in variables.items():
            self.set_variable(variable_name, value)
        self._fill_missing_optionals()

    def create_dvc_variables(self, output_dir, create_soucring_file: bool = True):
        """
        Create variable files for dvc. Optionally create file to source all variables at once
        """
        os.makedirs(output_dir, exist_ok=True)
        for variable_name in self._variables:
            filename = os.path.join(output_dir, variable_name)
            text = [YAMLConfigVariableType.to_plain_str(self._variables[variable_name])]
            list2file(text, filename, add_sep=False)
        if create_soucring_file:
            text = [f"{variable_name}=\"{YAMLConfigVariableType.to_plain_str(self._variables[variable_name])}\""
                    for variable_name, value in self._variables.items()]
            list2file(text, os.path.join(output_dir, self._dvc_all_variables_basename))

    def get_variable(self, variable_name):
        try:
            return self._variables[variable_name]
        except KeyError:
            raise UndefinedVariable(f"Variable '{variable_name}' is not defined in this config")

    def set_variable(self, variable_name, value):
        if variable_name in self.mandatory_variables:
            mandatory_variable = self.mandatory_variables[variable_name]
            if mandatory_variable.type:
                if not isinstance(value, mandatory_variable.type.value):
                    self._raise_type_error(mandatory_variable, value)
        elif variable_name in self.optional_variables:
            optional_variable = self.optional_variables[variable_name]
            if optional_variable.type and value is not None and \
                    not isinstance(value, optional_variable.type.value):
                self._raise_type_error(optional_variable, value)
        else:
            raise UndefinedVariable(f"Variable '{variable_name}' is not defined in this config")
        self._variables[variable_name] = value

    def _raise_type_error(self, variable, value):
        raise UnexpectedVariableTypeError(f"Expected type of variable '{variable.name}' is : "
                                          f"'{variable.type.value}' instead "
                                          f"'{type(value)}' in config "
                                          f"'{self._config_path}'")

    def _fill_missing_optionals(self):
        undefined_optional_variables = {optional_variable_name_object for
                                        optional_variable_name, optional_variable_name_object in
                                        self.optional_variables.items() if
                                        optional_variable_name not in self._variables}
        for undefined_optional_variable in undefined_optional_variables:
            self.set_variable(undefined_optional_variable.name, undefined_optional_variable.default_value)


class UndefinedVariable(ValueError):
    pass


class MissingVariablesError(ValueError):
    pass


class UnexpectedVariableTypeError(ValueError):
    pass
