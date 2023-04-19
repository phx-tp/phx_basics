from __future__ import annotations
import copy
import logging
import os
import subprocess
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
from typing import Union, Iterable

import yaml

from phx_general.file import file2list, check_file, list2file
from phx_general.git.phx_git_repository import PhxGitRepository
from phx_general.asr_annotations.annotated_audio import AnnotatedAudio
from phx_general.asr_annotations.annotation_segment import AnnotationSegment
from phx_general.asr_dictionary.dictionary import Dictionary
from phx_general.asr_annotations.phx_annotation_tags import PhxAnnotationTags
from phx_general.type import path_type
from phx_general.unit_conversion import hms2sec, sec2hms
from phx_general.wordset_iface import WordsetInterface
from phx_general.vad import Segmentation as VadSegmentation, VAD

_logger = logging.getLogger(__name__)


class PhxAnnotation(WordsetInterface):

    DEFAULT_AUDIO_DIR = "/media/marvin"
    FRAMERATE = 8000

    DATASET_REPOSITORY = "ASR-team/datasets.git"
    PHX_GITLAB_SERVER = "git@gitlab.int.phonexia.com:"
    UNKNOWN = "Unknown"
    TEST_LIST_BASENAME = 'test.list'

    class Metadata:
        _time_variables = {'test_audio_length', 'test_annotated_audio', 'train_audio_length', 'train_annotated_audio'}
        _default_string = "None"

        def __init__(self):
            self.language = self._default_string
            self.domain = self._default_string
            self.channel = self._default_string
            self.comment = self._default_string
            self.external_links = self._default_string
            self.test_audio_length = 0
            self.train_audio_length = 0
            self.test_annotated_audio = 0
            self.train_annotated_audio = 0

        def load(self, dataset_info):
            # load metadata
            with open(dataset_info, 'r') as finfo:
                try:
                    info = yaml.safe_load(finfo)
                    self.domain = info['domain']
                    self.channel = info['channel']
                    self.comment = info['comment']
                    self.language = info['language']
                    self.external_links = info['external_links']
                    self.test_audio_length = hms2sec(info['test_audio_length'])
                    self.test_annotated_audio = hms2sec(info['test_annotated_audio'])
                    self.train_audio_length = hms2sec(info['train_audio_length'])
                    self.train_annotated_audio = hms2sec(info['train_annotated_audio'])
                except Exception as e:
                    raise RuntimeError(f"'{dataset_info}' parsing error: {e}")

        def __str__(self):
            return yaml.dump(self.__get_write_dict())

        def write(self, dataset_info):
            # write metadata
            with open(dataset_info, 'w') as finfo:
                yaml.dump(self.__get_write_dict(), finfo)

        def merge(self, other_metadata):
            for name, val in self.__dict__.items():
                other_val = other_metadata.__dict__[name]
                if name in self._time_variables:
                    self.__dict__[name] = val + other_val
                    continue
                if val != other_val:
                    if val == self._default_string:
                        value = other_val
                    elif other_val == self._default_string:
                        value = val
                    else:
                        value = f"{val}; {other_val}"
                    self.__dict__[name] = value

        def merge_counterpart(self, other_metadata):
            # Concatenate metadata of train and test part of phxstm; other_metadata belongs to the other part of phxstm
            for name, val in self.__dict__.items():
                other_val = other_metadata.__dict__[name]
                if name in self._time_variables:
                    if other_val > val:
                        if val != 0.0:
                             raise ValueError("Are you merging train-test for the same dataset? Both parts have nonzero"
                                              " value for attribute '{name}'")
                        self.__dict__[name] = f"{other_val}"
                    continue
                
                if val != other_val:
                    raise ValueError("Are you merging train-test for the same dataset? Metadata differ for "
                                     "attribute '{name}': '{val} != '{other_val}'")

        def __get_write_dict(self):
            write_dict = dict()
            for name, val in sorted(self.__dict__.items()):
                if name in self._time_variables:
                    write_dict[name] = sec2hms(float(val))
                else:
                    write_dict[name] = val
            return write_dict

        """
        Defines segment of Phx Stm
        Most importantly it's the only place where tag_words are defined - always use this
        class' attributes when referring to unk/sil/hes
        """

    def __init__(self,
                 source_directory=None,
                 is_train: bool = True,
                 override_audio_paths: Union[str, None] = None,
                 phx_gitlab_server: str = PhxGitRepository.DEFAULT_PHX_GITLAB_SERVER,
                 repository_path: Union[str, None] = None,
                 framerate: int = FRAMERATE,
                 ):
        """
        @param source_directory Directory with phx_annotation and test.list or a git folder from datasets repository
                                if source_directory=None, empty PhxAnnotation is created, where data can be added later
        @param repository_path   If specified, this location is used to look for git repositories to download/copy files
                                from instead of cloning whole dataset directory
        """
        self._framerate = framerate
        self._annotated_audio = dict()  # { path: AnnotatedAudio }
        self.is_train = is_train

        # metadata
        self.metadata = PhxAnnotation.Metadata()

        if source_directory:
            self._source = source_directory  # remember for easier debugging
            self._dataset_name = PhxGitRepository.get_git_path_basename(source_directory)
            if PhxGitRepository.is_git_path(source_directory):
                # Download dataset from git into temp. folder and read PhxAnnotation from it
                with TemporaryDirectory() as tmp_dir:
                    self._download_from_git(phx_gitlab_server, source_directory, tmp_dir, repository_path)
                    self.load(tmp_dir)  # use git path as source
            else:
                # Load train or test phx_annotation directly
                self.load(source_directory)
        else:
            self._source = PhxAnnotation.UNKNOWN  # TODO shouldn't this be better emtpy string?
            self._dataset_name = PhxAnnotation.UNKNOWN  # TODO shouldn't this be better emtpy string?

        # will be used while reading audio paths from phx_annotation; if not None,'PhxAnnotation.default_audio_path'
        # portion of audio path gets overwritten by content of self._override_audio_path
        self.override_audio_paths = override_audio_paths

    @property
    def annotated_audio(self) -> dict[str, AnnotatedAudio]:
        return self._annotated_audio

    def get_voice_segmentation(self):
        """

        :return: (dict) segmentation
        """
        segmentation = dict()
        for annotated_audio in self._annotated_audio.values():
            segmentation[annotated_audio.path] = annotated_audio.get_voice_segmentation()
        return segmentation

    def get_words(self, omit_tags=False):
        """
        Returns set of all words that are contained in this class
        @return Set of all words in this (train/test) portion of phx annotation's source file
        """
        words = set()
        for annotated_audio in self._annotated_audio.values():
            words.update(annotated_audio.get_words())
        if omit_tags:
            words.difference_update(PhxAnnotationTags.ALL)
        return words

    def get_graphemes(self):
        """
        Get all used graphemes
        """
        graphemes = set()
        [graphemes.update(set(word)) for word in self.get_words(omit_tags=True)]
        return graphemes

    def get_text_for_lm(self):
        """
        Returns list of text lines (~segments) stored in phx annotation
        """
        text = list()
        for annotated_audio in self._annotated_audio.values():
            text.extend(annotated_audio.get_text_for_lm())
        return text

    def get_text_for_am(self, dictionary_wordset: set):
        """
        @param dicionary_wordset Set containing all words from dictionary for word filtering
        Returns list of text lines (~segments) stored in phx annotation
        """
        text = list()
        for annotated_audio in self._annotated_audio.values():
            text.extend(annotated_audio.get_text_for_am(dictionary_wordset))
        return text

    def get_audio_length(self):
        """
        Returns tuple (total_audio_length, annotated_audio_length)  annotated_audio_length ~ length of all segments
        """
        total_audio_length = 0.0
        annotated_audio_length = 0.0
        for af in self._annotated_audio.values():
            total_audio_length += af.get_length()
            annotated_audio_length += af.segments_length

        if self.is_train:
            self.metadata.train_audio_length = total_audio_length
            self.metadata.train_annotated_audio = annotated_audio_length
        else:
            self.metadata.test_audio_length = total_audio_length
            self.metadata.test_annotated_audio = annotated_audio_length

        return total_audio_length, annotated_audio_length

    def get_audio_paths(self):
        """
        Returns audio paths to all waves referenced by PhxAnnotation
        """
        return self._annotated_audio.keys()

    def get_file_ids(self):
        """
        Returns file id for all waves referenced by PhxAnnotation
        """
        return [aa.file_id for aa in self._annotated_audio.values()]

    def check(self, expected_graphemes: Union[Iterable[str], None] = None, permissive: bool = False, shallow: bool = False):
        """
        Checks whether there are not common mistakes/problems in the input phx_annotation
        @param expected_graphemes List of chars - allowed graphemes, if some other grapheme shall occur, error is thrown
        @param permissive If True, all checks that are not absolutely vital will generate warning instead of error
                         use with greatest care!
        @param shallow If True, physical data of wav files are not read - hashes are not generated, segment overlaps
                       and annotations past end (pre start) of the recording are not detected,
        """
        fail = False
        if permissive:
            # disable grapheme check
            expected_graphemes = None

        unfound_expected_graphemes = set()
        if expected_graphemes:
            unfound_expected_graphemes = set(expected_graphemes)

        audiofile_hashes = set()
        file_ids = set()
        for annotated_audio in self._annotated_audio.values():
            try:
                annotated_audio.check(shallow=shallow)
                if not shallow:
                    self._check_hash_duplicity(annotated_audio.path, annotated_audio.get_hash(), audiofile_hashes)

                self._check_fileid_duplicity(annotated_audio.path, annotated_audio.file_id, file_ids)

            except ValueError as e:
                _logger.error(f"Error while checking {self.get_name()}: '{e}'")
                fail = True
                continue

        spelling_detected = False
        for w in self.get_words():
            if re.match("<.*>", w):
                if w not in PhxAnnotationTags.ALL:
                    _logger.error(f"Unknown tag '{w}' encountered!")
                    fail = True
                else:
                    # some known tag ... do not grab its graphemes
                    continue

            if re.match("\[.*\]", w):
                continue  # ignore words in brackets

            if w == '-':
                _logger.error(f"Word '-' encountered - probably shouldn't be present")
                fail = True
                continue

            is_spelling = Dictionary.is_spelling(w)
            if is_spelling and not spelling_detected:
                # only print once
                _logger.warning(f"Spelling seems to be present")
                spelling_detected = True

            if expected_graphemes:
                for grapheme in w:
                    if grapheme not in expected_graphemes:
                        # expect '_' grapheme for spelling   "m_ i_ ch_ a_ l_" etc.
                        if grapheme == '_':
                            if is_spelling:
                                continue

                            fail = True
                            _logger.error(f"Character '_' allowed only for spelling. Is {w} really a spelling?")
                            continue

                        fail = True
                        msg = f"Grapheme '{grapheme}' of word '{w}' not among expected graphemes '[{' '.join(expected_graphemes)}]'"
                        _logger.error(msg)
                    else:
                        unfound_expected_graphemes.discard(grapheme)

        if not self.empty():
            if unfound_expected_graphemes:
                err = f"Some of expected graphemes '{', '.join(unfound_expected_graphemes)}' not found in "\
                      f"{'train' if self.is_train else 'test' } part of {self.get_name()} in '{self._source}'"
                if self.is_train:
                    _logger.error(err)
                    fail = True
                else:
                    _logger.warning(err)

            if fail:
                raise ValueError(f"Errors while checking {self.get_name()} - check stderr")

    def write(self, directory, mode="w", omit_metadata=False):
        """
        Writes phx annotation as a file.
        Paths prefix (as in self._paths_prefix) is automatically stripped from audio file paths
        @param directory Where to write/append the result - if it doesn't exist, gets created
        @param mode Can be either "w" or "a" to write or append. If you want to concatenate test and train PhxAnnotation
                    intances use "a" mode to write them into the same file
        @param omit_metadata If omit_metadata=True, dataset.info is not printed, moreover audio lengths for dataset
                             don't get computed - might be useful as an optimization in some parts of pipelines
                             where reading all physical files is not necessary
        """
        os.makedirs(directory, exist_ok=True)
        source_file = os.path.join(directory, self.get_source_file_name())
        testlist = os.path.join(directory, "test.list")
        dataset_info = os.path.join(directory, 'dataset.info')
        if mode not in ["w", "a"]:
            raise RuntimeError(f"Mode for writing the {self.get_name()} must be either 'w' to write or 'a' to append")

        with open(source_file, mode) as source_file_out, open(testlist, mode) as testlist_out:
            for af in sorted(self._annotated_audio.values()):
                audiopath = af.path
                if self._override_audio_paths:
                    audiopath = audiopath.replace(self._override_audio_paths, "")
                    audiopath = os.path.join(PhxAnnotation.DEFAULT_AUDIO_DIR, audiopath)

                af.sort_segments()
                for segment in af.segments:
                    source_file_out.write(f"{af.file_id}\tA\t{af.speaker}\t{segment.start_time:.2f}\t{segment.end_time:.2f}"
                                          f"\t<{audiopath}>\t{segment.get_text()}\n")

                if not self.is_train:
                    testlist_out.write(f"{audiopath}\n")

        if not omit_metadata:
            # compute audio lenghts for metadata if needed
            self.get_audio_length()

            if os.path.exists(dataset_info):
                other_info = PhxAnnotation.Metadata()
                other_info.load(dataset_info)
                self.metadata.merge_counterpart(other_info)
            self.metadata.write(dataset_info)

    def write_as_scoring_stm(self, filename, map_spelling=True):
        """
        Writes as stm for scoring by sclite - unfinished words/speech TAGS are placed into round brackets ()
        and TAGS representing silence are removed, moreover this stm doesn't contain paths to audio file
        @param filename where to write the resulting stm
        @param map_spelling  If True - remove underscores from spelling  a_ -> a  ;  ch_ ->  ch
        """
        with TemporaryDirectory() as tmpdir:
            tmp_stm = os.path.join(tmpdir, "stm")
            with open(tmp_stm, "w") as out:
                for af in sorted(self._annotated_audio.values()):
                    last_segment_end = 0.0
                    af.sort_segments()
                    for segment in af.segments:
                        score_words = []
                        for word in segment.get_text_for_scoring(map_spelling=map_spelling).split():
                            if word in PhxAnnotationTags.SILENCE_TAGS:
                                continue
                            if word in PhxAnnotationTags.NONSILENCE_TAGS:
                                # state we don't care what comes to that position in transcription - e.g. unknown word
                                word = f"({word})"

                            score_words.append(word)

                        if not score_words:
                            continue

                        # beware of comparing float values exactly
                        if segment.start_time - last_segment_end > 0.0001:
                            out.write(f"{af.file_id}\tA\t{af.speaker}\t{last_segment_end:.2f}\t{segment.start_time:.2f}"
                                      f"\tIGNORE_TIME_SEGMENT_IN_SCORING\n")

                        score_text = " ".join(score_words)
                        out.write(f"{af.file_id}\tA\t{af.speaker}\t{segment.start_time:.2f}\t{segment.end_time:.2f}\t{score_text}\n")
                        last_segment_end = segment.end_time

                    annotated_audio_end = af.get_length()
                    if annotated_audio_end - last_segment_end > 0.0001:
                        out.write(f"{af.file_id}\tA\t{af.speaker}\t{last_segment_end:.2f}\t{annotated_audio_end:.2f}"
                                  f"\tIGNORE_TIME_SEGMENT_IN_SCORING\n")

            # use bash to correctly sort stm for scoring  TODO -figure out how to do this in python
            with open(filename, "w") as stm:
                subprocess.run("sort +0 -1 +1 -2 +3nb -4".split(" ") + [tmp_stm], stdout=stm)

    def load(self, directory):
        """
        Loads PhxAnnotation class from given files
        """
        self._reset()
        self.load_metadata(directory)
        source_file = os.path.join(directory, self.get_source_file_name())
        check_file(source_file)
        fail = False
        re_time = re.compile(r"^\d+(?:\.\d+){0,1}$")
        re_audiopath = re.compile(r"^<[a-zA-Z0-9_\./-]+>$")
        re_channel = re.compile(r"^A$")
        re_text = re.compile(r"^\S+(?: \S+)*$")
        # paths to real location of test set files on dist
        test_audiofiles = self._source_test_list(directory)
        lines = file2list(source_file)
        for (line, line_num) in zip(lines, range(1, len(lines)+1)):
            if line.count('\t') != 6:
                _logger.error(f"{source_file}:{line_num} for line \"{line}\". Line should contain 7 columns separated "
                               " by TABs - have a look at https://gitlab.int.phonexia.com/ASR-team/datasets/-/blob/master/README.md")
                fail = True
                continue  # this wouldn't allow us to split the phx_annotation

            (file_id, channel, speaker, start, end, audiopath, text) = line.split('\t')
            # Check each column for formatting problems...
            for (column, (att_name, att, regexp)) in enumerate([('FileID', file_id, AnnotatedAudio.RE_FILE_ID),
                                                                ('ChannelID', channel, re_channel),
                                                                ('SpeakerID', speaker, AnnotatedAudio.RE_SPEAKER_ID),
                                                                ('SegmentStart', start, re_time),
                                                                ('SegmentEnd', end, re_time),
                                                                ('AudioPath', audiopath, re_audiopath),
                                                                ('AnnotationSegments', text, re_text)]):
                if not PhxAnnotation._check_parsed_column(source_file, line_num, column+1, att_name, att, regexp):
                    fail = True
            # transform to get real location of audio file on disk
            audiopath = os.path.normpath(audiopath.strip("<>"))
            if not audiopath.startswith(PhxAnnotation.DEFAULT_AUDIO_DIR):
                _logger.error(f"{source_file}:{line_num} for \"{line}\": "
                              f"Bad audio path. Does not start in '{PhxAnnotation.DEFAULT_AUDIO_DIR}'")
                fail = True
                continue

            # add segment based on info from test.list and whether we are in train or test portion of phx annotation
            if (audiopath in test_audiofiles) == (not self.is_train):
                try:
                    if audiopath not in self._annotated_audio:
                        self._annotated_audio[audiopath] = AnnotatedAudio(file_id, speaker, audiopath, self._framerate)
                    self._annotated_audio[audiopath].add_segment(AnnotationSegment(float(start), float(end), text.split()))
                except ValueError as e:
                    _logger.error(f"Error at {source_file}:{line_num} Error while creating AnnotatedAudio class "
                                  f"instance and adding segments: '{e}'")
                    fail = True

        unused_test_audiopaths = test_audiofiles.difference(self._annotated_audio.keys())
        if unused_test_audiopaths and not self.is_train:
            raise ValueError(f"{self.TEST_LIST_BASENAME} in {directory} contains unused audiopaths: "
                             f"{', '.join(unused_test_audiopaths)}. Please correct or remove them")
        if fail:
            raise RuntimeError(f"Error(s) occurred while loading {self.get_name()} from '{source_file}'!")

    @property
    def override_audio_paths(self):
        return self._override_audio_paths

    @override_audio_paths.setter
    def override_audio_paths(self, new_audio_dir: Union[str, None]):
        """
        Change default audio dir to new audio dir
        :param new_audio_dir:
        :return:
        """
        self._override_audio_paths = new_audio_dir
        if new_audio_dir:
            if len(self._annotated_audio) == 0:
                _logger.debug("Nothing to override.")
            else:
                for annotated_audio_path in self._annotated_audio.copy():
                    new_path = self.transform_audio_path(annotated_audio_path, new_audio_dir)
                    self._annotated_audio[new_path] = self._annotated_audio.pop(annotated_audio_path)
                    self._annotated_audio[new_path].path = new_path

    def load_metadata(self, directory):
        dataset_info = os.path.join(directory, 'dataset.info')
        check_file(dataset_info)
        self.metadata.load(dataset_info)

    def add_audio_segmentation(self, segmentation: VadSegmentation, permissive=True):
        """
        Creates AnnotatedAudio instances with empty segments.
        @param segmentation general.objects.vad.Segmentation (as returned e.g. by VAD)  @see general.objects.vad.Segmentation
                            Note, that if any file from segmentation is already present in PhxAnnotation an error is thrown
        @param permissive   If True, tries to load as many of the segmented audio as possible, in case of an error,
                            the audiofile is simply skipped
        """
        # no longer just this PhxAnnotation
        self._source += "+segmentation"
        self._dataset_name += "+segmentation"

        file_ids = set([af.file_id for af in self._annotated_audio.values()])
        audiofile_hashes = set([af.get_hash() for af in self._annotated_audio.values()])
        unk_id = 0
        has_error = False
        for path, segments in segmentation.items():
            if not segments:
                logging.warning(f"No voice segments for audio '{path}' - skipped")
                continue

            try:
                if not path.endswith(".wav"):
                    raise ValueError(f"Audio file in segmentation should have '*.wav' extension")

                if path in self._annotated_audio:
                    raise ValueError(f"Audio file at path '{path}' already present in {self.get_name()}! - Can't be added twice.")

                unk_id += 1
                file_id = os.path.splitext(os.path.basename(path))[0]  # get basename and strip *.wav
                annotated_audio = AnnotatedAudio(file_id, f"unk_speaker_{unk_id:05}", path, self._framerate)

                # check framerate and compute audio hash/length
                annotated_audio.read_and_check_physical_file()

                self._check_hash_duplicity(path, annotated_audio.get_hash(), audiofile_hashes)
                self._check_fileid_duplicity(path, annotated_audio.file_id, file_ids)

                for (start, end) in segments:
                    # adds a segment with empty text
                    annotated_audio.add_segment(AnnotationSegment(start, end, words=AnnotationSegment.EMPTY))

                self._annotated_audio[path] = annotated_audio

            except ValueError as e:
                if permissive:
                    _logger.warning(f"Audio file '{path}' skipped due to error: {e}")
                else:
                    _logger.error(e)
                    has_error = True

        if has_error:
            raise ValueError(f"Adding of segmentation into {self.get_name()} failed - check log")

    def merge(self, other_phx_annotation: PhxAnnotation):
        """
        Merges another PhxAnnotation into this one
        @param other_phx_annotation The PhxAnnotation to be merged into this one
        """
        if self.is_train != other_phx_annotation.is_train:
            raise ValueError("It is not possible to merge different types of PhxAnnotation. "
                             f"(self.is_train={self.is_train}) != (other.is_train={other_phx_annotation.is_train})")

        # no longer just this PhxAnnotation
        self._source += f"+{other_phx_annotation._source}"
        self._dataset_name += f"+{other_phx_annotation._dataset_name}"

        other_phx_annotation = copy.deepcopy(other_phx_annotation)
        if self.override_audio_paths != other_phx_annotation.override_audio_paths:
            raise ValueError(f"Value of 'override_audio_paths' differs. self._override_audio_paths="
                             f"{self.override_audio_paths}, merged={other_phx_annotation.override_audio_paths}")
        for af in other_phx_annotation._annotated_audio.values():
            # add segment based on info from test.list and whether we are in train or test portion of phx annotation
            if af.path not in self._annotated_audio:
                self._annotated_audio[af.path] = af
            else:
                raise ValueError(f"Failed to merge {self.get_name()} instances - audiopath '{af.path}' occurs twice")
        self.metadata.merge(other_phx_annotation.metadata)

    def get_dataset_name(self):
        """
        Return unique string identifier for dataset as source dirname
        :return: (string) source dirname
        """
        return self._dataset_name

    def empty(self):
        """Returns true if there is no annotated_audio/segments in the PhxAnnotation instance"""
        return len(self._annotated_audio) == 0

    def __str__(self):
        """
        Retrieve string info about PhxAnnotation set
        """
        self.get_audio_length()
        part = 'train' if self.is_train else 'test'
        part_del_regex = r'^test_.*\n?' if self.is_train else r'^train_.*\n?'
        metadata_str = str(self.metadata)
        metadata_str = re.sub(part_del_regex, '', metadata_str, flags=re.MULTILINE)

        info = f"{self.get_name()}: {self._source}\n" \
            f"part: {part}\n" \
            f"{metadata_str}"

        return info

    def get_annotated_audio_by_file_id(self, file_id):
        paths = self._get_audiopaths_by_file_id(file_id)
        if len(paths) == 0:
            return None
        if len(paths) != 1:
            raise ValueError(f"Multiple audio files '{paths}' with file id '{file_id}' in your {self.get_name()}")
        return self._annotated_audio[paths.pop()]

    def get_name(self):
        raise NotImplementedError('Please implement get_name() method in child class of PhxAnnotation')

    def get_source_file_name(self):
        raise NotImplementedError('Please implement get_source_file_name() method in child class of PhxAnnotation')

    def get_duplicate(self, other: PhxAnnotation):
        """
        Check self and other PhxAnnotationfor duplicities
        @param other Another PhxAnnotation to be checked for duplicates
        @return List of lists with duplicate filenames e.g.  [[name_self1, name_self2, name_other1], [name_other1, name_other2]]
        """
        # TODO do audio thumbnail and check them - not only hashes
        self_audiofile_hashes = set([af.get_hash() for af in self._annotated_audio.values()])
        other_audiofile_hashes = set([af.get_hash() for af in other._annotated_audio.values()])
        duplicate_hashes = self_audiofile_hashes.intersection(other_audiofile_hashes)
        duplicate = []
        if duplicate_hashes:
            for h in duplicate_hashes:
                d = []
                d.extend(self._get_audiopaths_by_hash(h))
                d.extend(other._get_audiopaths_by_hash(h))
                duplicate.append(d)
        return duplicate

    def try_to_fix_segment_times(self, threshold=0.02, use_physical_file=False):
        # tries to fix very small overlaps of segments (may be caused by annotator, or by slightly bad AM alignments for ctm)
        # if use_physical_file==True, reads true wave length and fixes segments accordingly
        for aa in self._annotated_audio.values():
            aa.try_to_fix_segment_times(threshold, use_physical_file)

    def get_source(self):
        return self._source

    def set_source(self, source):
        logging.warning(f'Re-setting source of {self.get_name()} - are you sure you know what you are doing?')
        self._source = source

    def get_grapheme_counts(self):
        grapheme_counts = Counter()
        for af in self._annotated_audio.values():
            grapheme_counts += Counter(af.get_grapheme_counts())

        # returns phonemes sorted from most common to least common
        return sorted(grapheme_counts.items(), key=lambda kv: (float(kv[1]), kv[0]), reverse=True)

    # ---------------------------   INTERNAL METHODS   -----------------------------------------------------------

    def _reset(self):
        self._annotated_audio.clear()
        self.metadata = PhxAnnotation.Metadata()

    def _download_from_git(self, phx_gitlab_server, source, tmp_dir, repository_path=None):
        _logger.info(f"Downloading input '{source}' from GIT")
        files_to_download = [self.get_source_file_name(), 'test.list', 'dataset.info']
        git_files_to_download = [PhxGitRepository.join_git_path(source, f) for f in files_to_download]
        phx_git = PhxGitRepository(server=phx_gitlab_server, repository='datasets', repo_path=repository_path)
        phx_git.download_files("string", git_files_to_download, tmp_dir)

    @staticmethod
    def transform_audio_path(audiopath, new_root):
        if audiopath.startswith(PhxAnnotation.DEFAULT_AUDIO_DIR):
            return os.path.normpath(os.path.join(new_root, os.path.relpath(audiopath, PhxAnnotation.DEFAULT_AUDIO_DIR)))
        else:
            raise ValueError(f"Can't transform audio path '{audiopath}' -"
                             f" path doesn't start with '{PhxAnnotation.DEFAULT_AUDIO_DIR}'")

    def _get_audiopaths_by_hash(self, hash):
        return sorted(list({af.path for af in self._annotated_audio.values() if af.get_hash() == hash}))

    def _get_audiopaths_by_file_id(self, file_id):
        return {af.path for af in self._annotated_audio.values() if af.file_id == file_id}

    def _check_hash_duplicity(self, path, audio_hash, audiofile_hashes_tmp_cache):
        # check audio file duplicities on a binary level
        if audio_hash in audiofile_hashes_tmp_cache:
            duplicate_audiopaths = self._get_audiopaths_by_hash(audio_hash)
            duplicate_audiopaths.append(path)
            raise ValueError(f"{self.get_name()} contains duplicate audio files (hash content is equal): "
                             f"'{', '.join(duplicate_audiopaths)}'")
        audiofile_hashes_tmp_cache.add(audio_hash)

    def _check_fileid_duplicity(self, path, file_id, file_ids_tmp_cache):
        # Check for file_id duplicities - might happen by mistake, would cause troubles in kaldi files generated
        # from such a phx_annotation
        if file_id in file_ids_tmp_cache:
            duplicate_audiopaths = self._get_audiopaths_by_file_id(file_id)
            duplicate_audiopaths.add(path)
            raise ValueError(f"Duplicate file_id '{file_id}': for file ids: '{', '.join(duplicate_audiopaths)}'")
        file_ids_tmp_cache.add(file_id)

    @staticmethod
    def _check_parsed_column(source_file, line_num, column, att_name, att, regexp):
        if not re.match(regexp, att):
            _logger.error(f"{source_file}:{line_num}: '{att_name}' (column {column}): '{att}' "
                          f"doesn't match regexp: r'{regexp.pattern}' - BAD ANNOTATION FORMAT!")
            return False
        return True

    @staticmethod
    def _get_speaker_id(recording_id, speaker):
        parts = recording_id.split("-")
        assert(len(parts) == 3)  # recoding id should be SET-FILE-CHANNEL
        rset = parts[0]
        return f"{rset}-{speaker}"

    @staticmethod
    def _get_utterance_id(recording_id, speaker, start, end):
        rset, rfile, rchannel = recording_id.split("-")
        start_str = '{:07d}'.format(int(start * 100))
        end_str = '{:07d}'.format(int(end * 100))
        return f"{rset}-{speaker}-{rfile}-{rchannel}-{start_str}_{end_str}"

    @staticmethod
    def _split_utterance_id(utterance_id):
        rset, speaker, rfile, rchannel, rstart_end = utterance_id.split("-")
        rstart, rend = rstart_end.split("_")
        start = float(rstart) / 100.0
        end = float(rend) / 100.0
        recording_id = f"{rset}-{rfile}-{rchannel}"
        return recording_id, speaker, start, end

    def _source_test_list(self, source_directory):
        test_list_path = os.path.join(source_directory, self.TEST_LIST_BASENAME)
        check_file(test_list_path)
        test_list = file2list(test_list_path)
        test_audiofiles = set()
        for path in test_list:
            path = os.path.normpath(path)
            if not path.startswith(PhxAnnotation.DEFAULT_AUDIO_DIR):
                raise RuntimeError(f"Bad audiopath '{path}' in {self.get_name()} - does not start with "
                                   f"'{PhxAnnotation.DEFAULT_AUDIO_DIR}'")
            test_audiofiles.add(path)

        if len(test_audiofiles) != len(test_list):
            duplicate_paths = [p for p in test_list if test_list.count(p) > 1]
            raise ValueError(f"{test_list_path} contains duplicate entries: {', '.join(duplicate_paths)}")
        return test_audiofiles

    def write_as_bsapi_transcriptions(self,
                                      output_directory: path_type,
                                      words_delimiter: str = "_",
                                      transcription_suffix: str = ".trn"):
        """
        Convert to ".trn" files
        """
        os.makedirs(output_directory, exist_ok=True)
        for wav_path, annotated_audio in self._annotated_audio.items():
            file_path = Path(output_directory) / f"{annotated_audio.file_id}{transcription_suffix}"
            output = list()
            for segment in annotated_audio.segments:
                output.append(f"{round(segment.start_time*VAD.HTK_TIME_MULTIPLICATION_CONSTANT)} "
                              f"{round(segment.end_time*VAD.HTK_TIME_MULTIPLICATION_CONSTANT)} "
                              f"{words_delimiter.join(segment.get_text().split())} 1 1 1")
            list2file(output, file_path)
            # start_time end_time word probability likelihood channel_index

