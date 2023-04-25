import hashlib
import logging
import multiprocessing
import shutil
from pathlib import Path

from tempfile import TemporaryDirectory, NamedTemporaryFile
import os

import numpy as np

from phx_general.asr_annotations.phx_annotation_tags import PhxAnnotationTags
from phx_general.bsapi.create_bsapi_cfg import ConfigGenerator
from phx_general.git.phx_git_repository import PhxGitRepository
from phx_general.lm.language_model import Arpa
from phx_general.shell import shell
from phx_general.file import list2file, file2list, check_file

from phx_general.cpu_utils import check_cores

_logger = logging.getLogger(__name__)


class G2P:

    # Do not modify this name it's used in am/create_unsupervised_adaptation_deploy.sh script
    # If True, local jinja template file is used, no need for downloading it from GIT
    # this file however needs to be provided by user
    _USE_TEMPLATE_FILE = False

    _KNOWN_TAGS = set(Arpa.tags).union(set(PhxAnnotationTags.ALL))

    MODEL_HEADER = b'\xd6\xfd\xb2~\x06\x00\x00\x00vector\x08\x00'
    BSAPI_COMMAND = "g2p"

    """
    Class for translating words to pronunciation
    @param bsapi_bin Path to BSAPI phxcmd binary
    @param g2p_cfg G2P configuration. Either a *.bs g2p filename you may use 
    """
    def __init__(self, phxcmd_bin, g2p_cfg, cores: int = 1):
        check_file(phxcmd_bin)
        self.phxcmd_bin = phxcmd_bin
        self.g2p_dict = list()
        self.untranslatable = set()
        self.delimiter = "\t"
        self._cores = check_cores(cores)
        self._g2p_cfg = g2p_cfg
        self._last_input_list_hash = None

    def get_dictionary(self, input_list):
        """
        Get list of tuples of words and its pronunciations translated by g2p
        Note that if a get_untranslatable() is called afterwards with the very same input list,
        cached results are returned.
        :return: list of tuples of words and its pronunciations translated by g2p
        """

        self._process(input_list)
        tuples = list()
        for line in sorted(self.g2p_dict):
            word, pronunciation = line.split(self.delimiter)
            tuples.append((word, pronunciation))
        return tuples

    def get_untranslatable(self, input_list):
        """
        Get sorted list of words that cant be translated
        Note that if a get_dictionary() is called afterwards with the very same input list,
        cached results are returned.
        :return: sorted list of words that cant be translated
        """
        self._process(input_list)
        return sorted(self.untranslatable)

    @staticmethod
    def _create_temp_input_file(directory, input_wordlist):
        """
        Create file for g2p binary as input
        :param temp: directory when input file is created
        :param input_list: (list) list of words
        :return: path to file with input wordlist
        """
        input_wordlist_file = os.path.join(directory, "tmp_list")
        list2file(input_wordlist, input_wordlist_file, add_sep=True)
        return input_wordlist_file

    def _run_g2p(self, g2p_conf, output_dir, input_file=None, input_list=None):
        """
        Run g2p
        :param g2p_conf: BSAPI g2p configuration file
        :param input_file: input file
        :param output_dir: output dictionary file
        :return: path to output dictionary file
        """
        assert input_file or input_list, "'input_file' or 'input_list' have to be set"
        assert not (input_file and input_list), "'input_file' and 'input_list' can't be set both"
        tmp_output = os.path.join(output_dir, "tmp_dict")
        cmd = [self.phxcmd_bin, G2P.BSAPI_COMMAND, "-c", g2p_conf, "-o", tmp_output]
        if input_file:
            cmd.extend(["-i", input_file])
        if input_list:
            cmd.extend(["-l", input_list])
        if self._cores:
            cmd.extend(["-j", str(self._cores)])
        shell(cmd)
        return tmp_output

    def _find_untranslatables(self, input_list):
        """
        Find which words from input list are not translated
        :param input_list: (list) wordlist
        :return: (list) untranslatable wordlist
        """
        output = set(input_list)
        for line in self.g2p_dict:
            output.discard(line.split(self.delimiter)[0])
        return output

    @staticmethod
    def _list_tolower(input_list):
        """
        Transfer all strings in list to lowercase
        :param input_list:
        :return: list of strings in lowercase
        """
        output = list()
        for word in input_list:
            output.append(word.lower())
        return output

    def _get_input_list_hash(self, input_list):
        input_list = self._list_tolower(input_list)
        input_list = list(set(input_list).difference(G2P._KNOWN_TAGS))

        return input_list, hashlib.md5('#'.join(input_list).encode('utf8')).digest()

    def _process(self, input_list):
        """
        Generate pronunciation for words in input list
        :param input_list: (list) wordlist
        """
        input_list, input_hash = self._get_input_list_hash(input_list)
        if input_hash == self._last_input_list_hash:
            return
        self._last_input_list_hash = input_hash
        with TemporaryDirectory() as tmp_dir:
            if self._cores == 1:
                tmp_input = self._create_temp_input_file(tmp_dir, input_list)
                tmp_out = self._run_g2p(self._g2p_cfg, tmp_dir, input_file=tmp_input)
                self.g2p_dict = file2list(tmp_out, strip=True)
            else:
                tmp_input_list = self._prepare_multithreads_inputs(tmp_dir, input_list)
                tmp_input_list_file = self._create_temp_input_file(tmp_dir, tmp_input_list)
                self._run_g2p(self._g2p_cfg, tmp_dir, input_list=tmp_input_list_file)
                self.g2p_dict = [word for file in tmp_input_list for word in file2list(file.rstrip(".txt"))]
            self.untranslatable.update(self._find_untranslatables(input_list))

    @staticmethod
    def create_data_config_directory(model, phonemes_list, graphemes_list, directory, label="test", version='x.x.x',
                                     dont_report_errors_immediately=False, phx_gitlab_server=PhxGitRepository.DEFAULT_PHX_GITLAB_SERVER):
        """
        Creates directory containing "data" and "settings" sub-directories
        containing files/symlinks according to input params, returns g2p config file location
        note that g2p config uses empty dictionary -> all words are generated by FSA
        @param model
        @param phonemes_list
        @param graphemes_list
        @param directory os.path.join(directory, 'settings', 'g2p_{label}.bs') is the location of resulting g2p config
        @param dont_report_errors_immediately causes g2p to report all the words for which the pronunciation wasn't generated
        @param phx_gitlab_server Use this server to download data from gitlab
        """
        if os.path.exists(directory):
            _logger.warning(f"G2P directory {directory} exists -> removing it")
            shutil.rmtree(directory)
        os.makedirs(directory)

        # create config
        g2p_cfg = os.path.join(directory, 'settings', f'g2p_{label}.bs')
        os.makedirs(os.path.dirname(g2p_cfg))
        if G2P._USE_TEMPLATE_FILE:
            # should be only True in case of unsupervised adaptation at customer's side
            ConfigGenerator('g2p', label, version, g2p_cfg,
                            g2p_dont_report_errors_immediately=dont_report_errors_immediately,
                            template_file="local/data/templates/g2p.bs.jinja2")
        else:
            # normal PHX scenario
            ConfigGenerator('g2p', label, version, g2p_cfg,
                            g2p_dont_report_errors_immediately=dont_report_errors_immediately,
                            phx_gitlab_server=phx_gitlab_server)

        # create data structure
        data_dir = os.path.join(directory, "data", f"models_{label}")
        os.makedirs(os.path.join(data_dir, 'dicts'))
        list2file(os.path.join(data_dir, "dicts", "phonemes"), phonemes_list)
        list2file(os.path.join(data_dir, "dicts", "graphemes"), graphemes_list)
        with open(os.path.join(data_dir, "dicts", "lexicon.txt"), 'a'):
            pass  # creates empty lexicon
        os.makedirs(os.path.join(data_dir, 'g2p'))
        os.symlink(model, os.path.join(data_dir, "g2p", "g2p.fst"))

        return g2p_cfg

    def _prepare_multithreads_inputs(self, tmp_dir, input_list):
        counter = 0
        input_files_list = list()
        for chunk in np.array_split(input_list, self._cores):
            chunk_file_path = os.path.join(tmp_dir, f"tmp_file{counter}.txt")
            list2file(chunk, chunk_file_path)
            input_files_list.append(chunk_file_path)
            counter += 1
        return input_files_list


class OpenfstG2P:
    """
    Class providing some operations directly above G2P *.fst model
    """

    def __init__(self, openfst_bin_folder, g2p_fst_model):
        """
        @param openfst_bin_folder Binaries of openfst providing operations above fst models
        @param g2p_fst_model G2P model in FST format
        """
        self._fstprint_binary = os.path.join(openfst_bin_folder, 'fstprint')
        self._model = g2p_fst_model
        self.phonemes = set()
        self.graphemes = set()

        with NamedTemporaryFile("w") as isym, NamedTemporaryFile("w") as osym:
            cmd = [self._fstprint_binary, f"--save_isymbols={isym.name}", f"--save_osymbols={osym.name}", self._model, "/dev/null"]
            shell(cmd)
            self.graphemes = OpenfstG2P._parse_fst_symbols_file(isym.name)
            self.phonemes = OpenfstG2P._parse_fst_symbols_file(osym.name)

    def get_phonemes(self):
        return self.phonemes

    def get_graphemes(self):
        return self.graphemes

    @staticmethod
    def _parse_fst_symbols_file(symbol_file):
        omit_symbols = {"<eps>", "__term__"}
        symbols = set()
        for line in file2list(symbol_file):
            columns = line.split()
            assert len(columns) == 2, f"'{symbol_file}' has not FST symbols format"
            symbols.add(columns[0])
        return sorted(symbols.difference(omit_symbols))

