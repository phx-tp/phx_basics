# import class to deal with TAGS
from __future__ import annotations
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Union, Iterable

from typeguard import typechecked

from phx_general.file import file2list, list2file
from phx_general.git.phx_git_repository import PhxGitRepository
from phx_general.asr_dictionary.g2p import G2P
from phx_general.asr_annotations.phx_annotation_tags import PhxAnnotationTags
from phx_general.type import path_type
from phx_general.wordset_iface import WordsetInterface

_logger = logging.getLogger(__name__)

# TODO grapheme/phoneme counts cache


@typechecked
class Dictionary(WordsetInterface):

    _MIN_GRAPHEME_OCCURENCES = 3
    _MIN_PHONEME_OCCURENCES = 10
    _MIN_WORDS = 500

    # ------------------------------- INTERFACE  --------------------------------------------------------

    def __init__(self,
                 source: Union[str, None] = None,
                 g2p: Union[G2P, None] = None,
                 phx_gitlab_server=PhxGitRepository.DEFAULT_PHX_GITLAB_SERVER,
                 repository_path: Union[str, None] = None):
        """
        Initializes dictionary.
        If a filename is provided, dictionary is loaded from a file.
        If the G2P (general.objects.g2p.G2P) object is provided, user will be able to add words
        without pronunciation into dictionary.
        @param source Path to file from which to read dictionary
                      or a git address in a "path_to_dict_in_dictionaries_repo#commit_hash" format
        @param g2p Instance of general.objects.G2P to use for pronunciation generation
        @param repository_path   If specified, this location is used to look for git repositories to download/copy files
                                from instead of cloning whole dataset directory
        """
        self._g2p = g2p
        self._source = source  # remember for easier debugging

        #  dicitonary with entries like { 'word': {['p r o n 1'], ['pr o n 2'}}
        #  maps word to set of pronunciations, where pronunciation is a string with space separated phonemes
        self._pronunciations = dict()

        if source:
            filename = source
            if PhxGitRepository.is_git_path(source):
                # Download from git into temp. folder and read Dictionary from it
                with TemporaryDirectory() as tmp_dir:
                    self.read(self._download_from_git(phx_gitlab_server, tmp_dir, repository_path))
            else:
                self.read(filename)

    @property
    def pronunciations(self):
        return self._pronunciations

    def set_g2p(self, g2p: G2P):
        """
        May be used to initialize G2P functionality later, after creation of the Dictionary
        @param g2p Instance of general.objects.g2p.G2P to use for pronunciation generation, use g2p=None to disable,
                   pronunciation-generating abilities of this Dictionary
        """
        self._g2p = g2p

    def merge(self, other_dict: Dictionary):
        """
        Merges all words from other_dict into this dictionary
        No checks on other_dict performed - user is free to merge checked dictionaries
        or to check the result once all required dictionaries are merged
        @param other_dict Dictionary to be merged into this dictionary
        """
        for (word, pronunciations) in other_dict._pronunciations.items():
            for pronunciation in pronunciations:
                self.add_pronunciation(word, pronunciation)  # not the most effective, but cleaner/more safe

    def get_words(self):
        """
        Implements WordsetInterface
        """
        return set(self._pronunciations.keys())

    def prepare_for_wordset(self, words: Iterable[str]):
        """
        Removes from dictionary all the words that are not in wordset
        Uses g2p to add all 'words' not present in dictionary already. Note that this may throw error
        if the g2p was not set a prior.
        @param words iterable of words
        @return Set of untranslated words that couldn't be added into Dictionary with current G2P
        """
        self.filter_by_words(words)
        return self._extend_by_words(words)

    def check(self,
              grapheme_permissive: bool = False,
              phoneme_permissive: bool = False):
        """
        Thorough check of dictionary - checks that
        @param grapheme_permissive If True, checks graphemes counts and generate warning instead of error use with the
        greatest care!
        @param phoneme_permissive If True, checks phonemes counts and generate warning instead of error use with the
        greatest care!
        @param grapheme_permissive Print warnings instead of errors for graphemes. Useful for special dictionaries.
        """
        min_grapheme_occurences = Dictionary._MIN_GRAPHEME_OCCURENCES
        min_phoneme_occurences = Dictionary._MIN_PHONEME_OCCURENCES
        min_words = Dictionary._MIN_WORDS

        fail = False
        # word count
        if len(self._pronunciations) < min_words:
            _logger.warning(f"You have less than {Dictionary._MIN_WORDS} words in Dictionary! - is there a problem?")

        # graphemes
        bad_graphemes = [(g, c) for (g, c) in self.get_grapheme_counts() if c < min_grapheme_occurences]
        grapheme_error_print_fn = _logger.warning if grapheme_permissive else _logger.error
        for (g, c) in bad_graphemes:
            grapheme_error_print_fn(f"Grapheme '{g}' occurs less than {Dictionary._MIN_GRAPHEME_OCCURENCES} times in "
                                    f"dictionary - occurred {c} times")
            if not grapheme_permissive:
                fail = True

        # phonemes
        bad_phonemes = [(p, c) for (p, c) in self.get_phoneme_counts() if c < min_phoneme_occurences]
        phoneme_error_print_fn = _logger.warning if phoneme_permissive else _logger.error
        for (p, c) in bad_phonemes:
            phoneme_error_print_fn(f"Phoneme '{p}' occurs less than {Dictionary._MIN_PHONEME_OCCURENCES} times in "
                                   f"dictionary - occurred {c} times")
            if not phoneme_permissive:
                fail = True

        if fail:
            raise RuntimeError(f"Error(s) occurred while checking dictionary '{self._source}'!")

    def get_pronunciation_counts(self):
        """
        Returns list of pairs (word, count) to detect words with multiple pronunciations
        The pairs are sorted so that words with the most pronunciations are first
        """
        counts = []
        for (word, pronunciations) in self._pronunciations.items():
            counts.append((word, len(pronunciations)))

        return sorted(counts, key=lambda pair: pair[1], reverse=True)

    def get_graphemes(self):
        """
        Return list of graphemes
        """
        graphemes = set()
        for word in self._pronunciations:
            for grapheme in word:
                graphemes.add(grapheme)
        return graphemes

    def get_grapheme_counts(self):
        """
        Return list of pairs (grapheme, count) sorted from the most common grapheme to least common
        """
        counts = dict()
        for word in self._pronunciations:
            for grapheme in word:
                if grapheme not in counts:
                    counts[grapheme] = 0
                counts[grapheme] += 1
        return sorted(counts.items(), key=lambda kv: (float(kv[1]), kv[0]), reverse=True)

    def get_phonemes(self):
        """
        Return list of phonemes
        """
        phonemes = set()
        for word_pronunciations in self._pronunciations.values():
            for pronunciation in word_pronunciations:
                for phoneme in pronunciation.split():
                    phonemes.add(phoneme)
        return list(phonemes)

    def get_phoneme_counts(self):
        """
        Return list of pairs (phoneme, count) sorted from the most common phoneme to least common
        """
        counts = dict()
        for word_pronunciations in self._pronunciations.values():
            for pronunciation in word_pronunciations:
                for phoneme in pronunciation.split():
                    if phoneme not in counts:
                        counts[phoneme] = 0
                    counts[phoneme] += 1
        return sorted(counts.items(), key=lambda kv: (float(kv[1]), kv[0]), reverse=True)

    def write(self, filename: path_type, add_tags: bool = True):
        """
        Writes a dictionary to file.
        @param filename Path where to store dictionary as file
        @param add_tags If true, the TAGS (as defined in general.objects.phx_stm.PhxStm) and their pronunciations
                        are added into
                        e.g. for tag word <tag> the line  '<tag>   tag' is added
        """
        lines = []
        if add_tags:
            for tag in PhxAnnotationTags.ALL:
                lines.append(f"{tag}\t{tag.strip('<>')}")

        for (word, pronunciations) in sorted(self._pronunciations.items()):
            lines.extend([f"{word}\t{pronunciation}" for pronunciation in sorted(pronunciations)])
        list2file(filename, lines)

    def read(self, filename):
        """
        Loads a dictionary from file. Strips any TAGS present in dictionary.
        Checks basic dictionary line formatting conventions
        @param filename
        """
        assert Path(filename).is_file(), filename
        lines = file2list(filename)
        fail = False
        for (line, line_num) in zip(lines, range(1, len(lines)+1)):
            # Format of dict is "word<TAB>phoneme1<SPACE>phoneme2<SPACE>...phonemeN
            if not re.match("^\S+\t(\S+ )*\S+$", line):
                _logger.error(f"{filename}:{line_num} for \"{line}\": Doesn't match pattern \"^\S+\\t(\S )*\S$\" - "
                              f"Word must be separated by TAB from pronunciation, phonemes in "
                              f"pronunciation are separated by spaces, no space allowed at the end of line")
                fail = True
                continue

            (word, pronunciation) = line.split('\t')

            if word[-1] == "\r":
                _logger.error(f"{filename}:{line_num} for \"{line}\": Word ends with carriage return character '\\r' - "
                              f"fix line endings from other OS! Line should end with '\\n' character.")
                fail = True
                continue

            if word.lower() != word:
                _logger.error(f"{filename}:{line_num} for \"{line}\": Word '{word}' is not lowercase")
                fail = True
                continue

            if word in PhxAnnotationTags.ALL:
                _logger.debug(f"Stripping tag! File {filename}:{line_num} at '{line}'")
                continue

            self.add_pronunciation(word, pronunciation)

        if fail:
            raise RuntimeError(f"Error(s) occurred while loading dictionary '{self._source}'!")

    def add_pronunciation(self, word: str, pronunciation: str):
        """
        Adds single word with pronunciation into dictionary
        @param word String word
        @param pronunciation String pronunciation (phonemes separated by spaces e.g. 'A0 F A1 r T')
        """
        word = word.strip()
        pronunciation = pronunciation.strip()
        if " " in word:
            raise ValueError("Word contains space, this is not allowed")

        if not word:
            raise ValueError("Cannot add pronunciation for empty word")

        if not pronunciation:
            raise ValueError(f"Cannot add empty pronunciation (for word '{word}')")

        if " " in pronunciation.split():
            raise ValueError(f"Pronunciation '{pronunciation}' contains empty phoneme! "
                             "- use only one space to separate phonemes")

        try:
            if pronunciation in self._pronunciations[word]:
                _logger.warning(f"Pronunciation '{' '.join(pronunciation)}' of word '{word}'"
                                f" is already present in a dictionary -> not added twice")

            self._pronunciations[word].add(pronunciation)
        except KeyError:
            self._pronunciations[word] = {pronunciation}

    def get_pronunciations(self, word):
        return self._pronunciations[word]

    def filter_by_words(self, words):
        """
        Removes from dictionary all of the words contained in supplied iterable
        """

        to_be_removed = list()
        for w in self._pronunciations.keys():
            if w not in words:
                to_be_removed.append(w)

        for w in to_be_removed:
            self._pronunciations.pop(w)

    def map_spelling(self):
        """
        Removes '_' char from spelling in form [a-z]{1-2}_
        e.g.   a_  -> a
              ch_  -> ch
        Irreversible operation modifying internal state of dictionary object!
        """
        new_pronunciations = defaultdict(set)
        for w, prons in self._pronunciations.items():
            if Dictionary.is_spelling(w):
                w = w.rstrip("_")
            new_pronunciations[w].update(prons)

        self._pronunciations = new_pronunciations

    # ------------------------------- INTERNAL FUNCTIONS --------------------------------------------------------

    def _extend_by_words(self, words):
        """
        Adds all the words from supplied iterable that aren't in dictionary already, pronunciation is generated by G2P
        if initialized, error thrown otherwise
        """
        if self._g2p is None:
            raise RuntimeError("G2P was not properly initialized. Please use set_g2p() method or"
                               "pass a general.objects.g2p.G2P instance in contructor.")

        # Do not try to translate foreign/trash words by G2P
        words_f = set([w for w in words if w[0] != "[" and w[-1] != "]" ])

        oov_words = words_f.difference(set(self._pronunciations.keys()))

        for (word, pronunciation) in self._g2p.get_dictionary(oov_words):
            self.add_pronunciation(word, pronunciation)

        return self._g2p.get_untranslatable(oov_words)

    def _download_from_git(self, phx_gitlab_server, tmp_dir, repository_path):
        _logger.info(f"Downloading dictionary '{self._source}' from GIT")
        phx_git = PhxGitRepository(server=phx_gitlab_server, repository='dictionaries', repo_path=repository_path)
        phx_git.download_files("string", [self._source], tmp_dir)
        return os.path.join(tmp_dir, os.path.basename(self._source.split("#")[0]))

    @staticmethod
    def is_spelling(word):
        if not word.endswith('_'):
            return False

        if len(word) > 4:
            # ignore long words ending with _ -> do not consider as spelling
            return False

        return True
