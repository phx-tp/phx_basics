import math
import os
import re
import logging

import typing

from phx_general.file import mkpdirp, GzipOpener, check_file
from phx_general.wordset_iface import WordsetInterface

_logger = logging.getLogger(__name__)


class Ngram:
    no_backoff_value = math.nan
    smallest_log_probability = float(-99)
    _threshold_log_probability = -98.9

    def __init__(self):
        self._word = str()
        self._history = tuple()
        self._count = int()
        self._log_probability = float()
        self._log_back_off = float()

    @property
    def word(self):
        return self._word

    @word.setter
    def word(self, w):
        assert type(w) == str
        self._word = w

    @property
    def history(self) -> tuple[str]:
        return self._history

    @history.setter
    def history(self, h: tuple[str]):
        assert type(h) == tuple
        self._history = h

    @property
    def log_probability(self):
        return self._log_probability

    @log_probability.setter
    def log_probability(self, value):
        assert type(value) == float
        if value < self._threshold_log_probability:
            self._log_probability = self.smallest_log_probability
        if value > 0:
            raise PositiveLogProbabilityError("Can't set positive number as log probability")
        else:
            self._log_probability = value

    @property
    def probability(self):
        return self._log_p2prob(self.log_probability)

    @property
    def log_back_off(self):
        return self._log_back_off

    @log_back_off.setter
    def log_back_off(self, value):
        assert isinstance(value, float) or value is None, f"Value type: {type(value)}"
        if value is None:
            self._log_back_off = value
        elif value < self._threshold_log_probability:
            self._log_back_off = self.smallest_log_probability
        elif value > 0:
            _logger.warning(f"Can't set positive number as log back-off: {value}")
            self._log_back_off = value
        elif math.isnan(value):
            self._log_back_off = math.nan
        else:
            self._log_back_off = value

    @property
    def back_off(self):
        if self.log_back_off is None:
            return None
        elif math.isnan(self.log_back_off):
            return self.log_back_off
        else:
            return self._log_p2prob(self.log_back_off)

    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, value):
        assert isinstance(value, int) or value is None
        self._count = value

    @property
    def history_order(self):
        return len(self.history)

    @property
    def order(self):
        return self.history_order + 1

    def __eq__(self, other):
        return self.word == other.word and self.history == other.history

    def __hash__(self):
        return hash(self.get_word_sequence())

    def __lt__(self, other):
        return self.word < other.word

    def __repr__(self):
        return " ".join(self.get_word_sequence())

    @classmethod
    def _log_p2prob(cls, log_probability):
        """
        convert logarithmic probability to 'linear' probability
        :param log_probability: input log probability
        :return: probability
        """
        if log_probability < cls._threshold_log_probability:
            return 0.0
        else:
            return pow(10, log_probability)

    @classmethod
    def prob2log_p(cls, probability):
        """
        convert 'linear' probability to logarithmic probability
        :param probability: input probability
        :return: logarithmic probability
        """
        if probability == 0.0:
            return cls.smallest_log_probability
        else:
            return math.log(probability, 10)

    def accumulate(self, ngram):
        """
        accumulate ngram. first check if history and word of input ngram fits, secondly sum probabilities and sum
        counts if input and this ngram have non-zero count, else set counts to None, finally set back-off to None,
        because its not possible to simply accumulate back-offs, those have to be counted separately
        :param ngram:
        :return:
        """
        assert isinstance(ngram, Ngram)
        assert self.word == ngram.word
        assert self.history == ngram.history
        logging.debug(f"Acumulating ngram: word={self.word} history={' '.join(self.history)}")
        if self.count is None or ngram.count is None:
            logging.debug(f"No count for accumulation for ngram '{str(self)}'")
            self.count = None
        else:
            self.count += ngram.count
        self.log_probability = self.prob2log_p(self.probability + ngram.probability)
        self.log_back_off = None

    def load_arpa_line(self, line: str):
        """
        load ngram from line in Arpa format splitted by whitespaces
        :param line: (str) line in Arpa format splitted by whitespace
        :return:
        """
        assert type(line) == str
        columns = line.rstrip().split("\t")
        assert len(columns) in {2, 3}, "Arpa lines have to be separated by tabulator and have to have 2 or 3 columns"
        try:
            self.log_probability = float(columns[0])
        except ValueError:
            raise ValueError(f"First item from input list has to be convertible to float ({columns[0]})")
        if len(columns) == 3:
            # try:
            self.log_back_off = float(columns[-1])
            # except PositiveLogProbabilityError as e:
            #     raise PositiveLogProbabilityError(f"Setting positive log prob backoff from line: {line}") from e
        else:
            self.log_back_off = None
        words = columns[1].split()
        self.word = words.pop(-1)
        self.history = tuple(words)
        self.count = None

    def get_word_sequence(self) -> tuple[str]:
        """
        get sequence of words in tuple
        :return: tuple - sequence of words
        """
        return self._history + (self._word,)

    def map_word(self, old_word, new_word):
        return_value = False
        if old_word in self.history:
            _logger.debug(f"history before mapping: {self.history}")
            hh = tuple(map(lambda x: x if x != old_word else new_word, self.history))
            _logger.debug(f"history after mapping: {hh}")
            self.history = hh
            self.log_back_off = None
            return_value = True
        if old_word == self.word:
            self.word = new_word
            self.log_back_off = None
            return_value = True
        return return_value


class LanguageModel(GzipOpener):
    _backoff_recount_tolerance = 1e-7

    def __init__(self):
        """
        data structure: list(dict(dict(Ngram)))
        list store ngrams by order , respective index of list is order of ngram history
        first dict key is history by chunked to tuple of strings
        second dict key is word as string
        """
        self._data = list()  # list(dict(dict())) # _data[history_order][history][word] = Ngram

    @property
    def order(self):
        return len(self._data)

    @property
    def ngram_iterator(self):
        return (ngram for history_order in range(0, self.order) for history in self._data[history_order]
                     for ngram in self._data[history_order][history].values())

    def load_arpa(self, arpa_path):
        """
        Load LM from file in ARPA format
        :param arpa_path: path to input file
        :return:
        """
        ngram_counts = list()
        regexp_ngram = re.compile("\\\\[0-9]-grams:\\s*")  # e.g.: \1-grams:
        with self.open_file(arpa_path) as fin:
            try:
                while True:
                    arpa_line = fin.readline()
                    columns = arpa_line.split()
                    if len(columns) == 0:
                        continue
                    elif len(columns) == 1:
                        tag = columns[0]
                        if regexp_ngram.match(tag):
                            continue
                        elif tag == '\\data\\':
                            continue
                        elif tag == "\\end\\":
                            break
                        else:
                            raise CorruptedArpaFormatError(f"Unexpected line in Arpa: '{arpa_line}'")
                    elif columns[0].startswith("ngram"):
                        ngram_counts.append(int(columns[1].split("=")[1]))
                        continue
                    else:
                        ngram = Ngram()
                        ngram.load_arpa_line(arpa_line)
                        self._add_ngram(ngram)
            except Exception as e:
                raise CorruptedArpaFormatError(f"File '{arpa_path}' doesn't look like LM in ARPA format: {e}")
        if self.order != len(ngram_counts):
            raise CorruptedArpaFormatError(f"Loaded LM order ({self.order}) differs to order specified by ARPA header "
                                           f"({len(ngram_counts)}) in '{arpa_path}'")
        if len(self._data[0]) == 0:
            raise CorruptedArpaFormatError(f"Unigrams are empty after loading file '{arpa_path}'.")

    def _add_ngram(self, ngram: Ngram):
        assert isinstance(ngram, Ngram)
        try:
            self.get_ngram(ngram.get_word_sequence()).accumulate(ngram)
        except TooHighOrder:
            if (self.order + 1) != ngram.order:
                raise ValueError("Unexpected loading of data. Add ngrams from low order to high order.")
            else:
                self._data.append({ngram.history: {ngram.word: ngram}})
        except MissingNgram:
            try:
                self._data[ngram.history_order][ngram.history][ngram.word] = ngram
            except KeyError:
                self._data[ngram.history_order][ngram.history] = {ngram.word: ngram}

    def get_ngram(self, word_sequence) -> Ngram:
        assert len(word_sequence) > 0
        try:
            history = word_sequence[:-1]
            word = word_sequence[-1]
            return self._data[len(history)][history][word]
        except KeyError:
            raise MissingNgram(f"No ngram found with word sequence'{word_sequence}'")
        except IndexError:
            raise TooHighOrder(f"LM doesn't contain any ngram with required order '{len(word_sequence)}'")

    def delete_ngram(self, word_sequence):
        assert len(word_sequence) > 0
        try:
            history = word_sequence[:-1]
            word = word_sequence[-1]
            del self._data[len(history)][history][word]
        except (KeyError, IndexError):
            raise MissingNgram(f"Ngram '{word_sequence}' is missing therefore can't be deleted")

    def map_word(self, old_word, new_word, recount_back_offs=True):
        deletion_sequences = set()
        new_ngrams = set()
        for ngram in self.ngram_iterator:
            old_sequence = ngram.get_word_sequence()
            if ngram.map_word(old_word, new_word):
                try:
                    self.get_ngram(ngram.get_word_sequence()).accumulate(ngram)
                except MissingNgram:
                    new_ngrams.add(ngram)
                deletion_sequences.add(old_sequence)
        for new_ngram in new_ngrams:
            self._add_ngram(new_ngram)
        for deletion_sequence in deletion_sequences:
            self.delete_ngram(deletion_sequence)
        if recount_back_offs:
            self.recount_back_offs(True)

    def recount_back_offs(self, only_missing: bool = True, check: bool = False):
        """
        Recount back off probabilities for all ngrams with None back off probabilities
        """
        tolerance = self._backoff_recount_tolerance if check else None
        if only_missing:
            for ngram in self.ngram_iterator:
                if ngram.log_back_off is None or ngram.log_back_off >= 0:
                    _logger.debug(f"Ngram '{ngram}' backoff is None or bigger than 0 -> recounting backoff.")
                    ngram.log_back_off = self.count_log_backoff(ngram, tolerance)
        else:
            for ngram in self.ngram_iterator:
                ngram.log_back_off = self.count_log_backoff(ngram, tolerance)

    def count_log_backoff(self, input_ngram: Ngram, tolerance=None):
        if input_ngram.order == self.order or input_ngram.word in {"</s>"}:
            return Ngram.no_backoff_value
        else:
            numerator = 1
            denominator = 1
            try:
                ngrams_with_input_ngram_history = self._data[input_ngram.order][input_ngram.get_word_sequence()].values()
            except KeyError as e:
                _logger.debug(f"No ngrams with history '{input_ngram}'")
                return Ngram.no_backoff_value
            for word_ngram in ngrams_with_input_ngram_history:
                numerator -= word_ngram.probability
                denominator -= self.get_ngram(word_ngram.get_word_sequence()[1:]).probability
            new_log_backoff = Ngram.prob2log_p(numerator) - Ngram.prob2log_p(denominator)
            old_log_backoff = self.get_ngram(input_ngram.get_word_sequence()).log_back_off
            if tolerance and old_log_backoff and not math.isclose(old_log_backoff, new_log_backoff, abs_tol=tolerance):
                _logger.warning(f"Counted backoff ({new_log_backoff}) and original backoff "
                                f"({self.get_ngram(input_ngram.get_word_sequence()).log_back_off}) "
                                f"differs more than tolerance for ngram '{input_ngram}'")
            return new_log_backoff

    def sums(self):
        """
        just for checking - delete me
        """
        for history_order in range(0, len(self._data)):
            for history in self._data[history_order]:
                for ngram in self._data[history_order][history].values():
                    self.count_log_backoff(ngram, 1e-7)

    def write_arpa(self, output_file_path):
        mkpdirp(output_file_path)
        with open(output_file_path, "w") as fout:
            # header
            fout.write(f"{os.linesep}\\data\\{os.linesep}")
            for order in range(1, self.order+1):
                fout.write(f"ngram {order}={self._get_ngram_count(order)}{os.linesep}")
            # body
            for order in range(1, self.order+1):
                fout.write(f"{os.linesep}\\{order}-grams:{os.linesep}")
                for history in sorted(self._data[order-1]):
                    for ngram in sorted(self._data[order-1][history].values()):
                        if ngram.back_off is None:
                            raise ValueError(f"Back off for ngram '{ngram}' is None. Recount backoff(s) before write.")
                        ending = os.linesep if math.isnan(ngram.log_back_off) else f"\t{ngram.log_back_off}{os.linesep}"
                        fout.write(f"{ngram.log_probability}\t{ngram}{ending}")
            fout.write(f"{os.linesep}\\end\\")

    def _get_ngram_count(self, order):
        ngram_count = 0
        for words in self._data[order-1].values():
            ngram_count += len(words)
        return ngram_count


class CorruptedArpaFormatError(ValueError):
    pass


class MissingNgram(ValueError):
    pass


class TooHighOrder(ValueError):
    pass


class PositiveLogProbabilityError(ValueError):
    pass


class Arpa(WordsetInterface, GzipOpener):
    suffix = ".arpa"
    start_of_sentence = "<s>"
    end_of_sentence = "</s>"
    unknown_word = "<unk>"
    tags = {start_of_sentence, end_of_sentence, unknown_word}
    hesitation = "<hes>"
    silence = "<sil>"
    optional_tags = {hesitation, silence}
    data_section_start = "\\data\\"

    def __init__(self, lm_path):
        """
        Initializes language model.
        Note that data are not read into memory as the size of Arpa might be big.
        @param lm_path Path to language model. Can be either "*.arpa" or "*.arpa.gz"
                       In case lm_path=="*.arpa.gz", it gets decompressed into temporary folder in __init__()
        """
        check_file(lm_path)
        self._lm_path = lm_path
        is_arpa = False
        with self.open_file(self._lm_path) as fin:
            for i in range(5):
                line = fin.readline()
                if line.startswith(Arpa.data_section_start):
                    is_arpa = True

        if not is_arpa:
            raise ValueError(f"Input '{lm_path}' doesn't seem to be arpa")

    @staticmethod
    def get_log10(p):
        return f"{math.log10(p):.6}"

    def get_words(self, omit_tags=False):
        words = set()
        get_uni = False
        with self.open_file(self._lm_path) as fin:
            line = fin.readline()
            try:
                while line:
                    line = line.strip().split()
                    if len(line) == 0:
                        if get_uni:
                            break
                        else:
                            line = fin.readline()
                            continue
                    if get_uni:
                        words.add(line[1])
                    if line[0] == "\\1-grams:":
                        get_uni = True
                    line = fin.readline()
            except Exception as e:
                raise ValueError(f"Wrong arpa format: {line}")
        if omit_tags:
            words.difference_update(self.tags)
            words.difference_update(self.optional_tags)
        return words

    def get_sum_ngrams(self):
        """
        Get sum of ngrams from header of arpa
        :return: sum of all ngrams
        """
        sum_ = 0
        with self.open_file(self._lm_path) as fin:
            for line in fin:
                if line.find("ngram ") == 0:
                    try:
                        sum_ += int(line.strip().split("=")[1])
                    except ValueError:
                        raise ValueError(f"Wrong format in head of arpa file in line: '{self._lm_path}'")
                if line.strip() == "\\1-grams:":
                    break
        return sum_

    def get_unigrams_count(self):
        """
        Get count of unigrams
        :return: count of unigrams
        """
        counter = 0
        with self.open_file(self._lm_path) as fin:
            for line in fin:
                counter += 1
                if line.find("ngram 1=") == 0:
                    try:
                        return int(line.strip().split("=")[1])
                    except ValueError:
                        raise ValueError(f"Wrong format in head of arpa file in line: '{self._lm_path}'")
                if counter == 10:
                    raise ValueError(f"File '{self._lm_path}' does not look like LM in arpa format")

    def get_unigrams(self):
        words = dict()
        get_uni = False
        with self.open_file(self._lm_path) as fin:
            line = fin.readline()
            try:
                while line:
                    line = line.strip().split()
                    if len(line) == 0:
                        if get_uni:
                            break
                        else:
                            line = fin.readline()
                            continue
                    if get_uni:
                        words[line[1]] = float(line[0])
                    if line[0] == "\\1-grams:":
                        get_uni = True
                    line = fin.readline()
            except Exception as e:
                raise ValueError("Wrong arpa format. ({})".format(line))
        return words

    def get_ngram_counts(self):
        output = list()
        with self.open_file(self._lm_path) as fin:
            line = fin.readline()
            while line:
                if line.find("ngram ") == 0:
                    output.append(line.strip())
                if line == "\\1-grams:":
                    break
                line = fin.readline()
        return output

    def check(self, wordset: WordsetInterface, omit_annotations_tags=False):
        """
        Checks that all words from ARPA are present in wordset
        @param wordset Class that implements general.objects.wordset_iface.WordsetInterface
        """
        should_fail = False
        wordset_words = wordset.get_words()
        wordset_words.update(Arpa.tags)
        if omit_annotations_tags:
            wordset_words.update(Arpa.optional_tags)
        with self.open_file(self._lm_path) as fin:
            in_unigram_section = False
            line_num = 0
            for l in fin:
                try:
                    line = l.strip().split()
                    line_num += 1
                    if len(line) == 0:
                        if in_unigram_section:
                            break
                        else:
                            continue
                    if in_unigram_section:
                        w = line[1]
                        if w != w.lower():
                            raise Exception(f"Word '{w}' is not lowercase")
                        if w not in wordset_words and w not in Arpa.tags:
                            raise Exception(f"Word '{w}' not present in supplied wordset")
                    if line[0] == "\\1-grams:":
                        in_unigram_section = True
                except Exception as e:
                    logging.error(f"Problem in ARPA at {self._lm_path}:{line_num} - '{l.strip()}' -  {e}")
                    should_fail = True

        if should_fail:
            raise ValueError("ARPA check failed, correct errors listed above")

    def get_graphemes(self):
        """
        Get all used graphemes
        """
        graphemes = set()
        [graphemes.update(set(word)) for word in self.get_words(omit_tags=True)]
        return graphemes

    def re_sub_low_memory(self, output_arpa_path, regex, replacement):
        assert isinstance(regex, typing.Pattern)
        with self.open_file(self._lm_path) as fin, open(output_arpa_path, "w") as fout:
            line = fin.readline()
            try:
                while line:
                    fout.write(regex.sub(replacement, line))
                    line = fin.readline()
            except Exception as e:
                raise ValueError("Wrong arpa format. ({})".format(line))
