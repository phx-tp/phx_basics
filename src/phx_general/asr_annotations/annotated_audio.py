import hashlib
import logging
import os
import re
import wave
from collections import Counter

from typeguard import typechecked

from phx_general.asr_annotations.annotation_segment import AnnotationSegment
from phx_general.file import check_file
from phx_general.vad import VAD

_logger = logging.getLogger(__name__)

@typechecked
class AnnotatedAudio:

    BSAPI_VOICE_LABEL = "voice"
    RE_FILE_ID = re.compile("^[a-zA-Z0-9_]+-[a-zA-Z0-9_.]+$")
    RE_SPEAKER_ID = re.compile(r"^[a-zA-Z0-9_]+$")

    # Do not modify this name it's used in am/create_unsupervised_adaptation_deploy.sh script
    # Maximum length of segment in seconds, can be lowered to protect from very long segments which
    # may clog utterance processing in Kaldi
    _MAX_SEGMENT_LENGTH = 9999999.0

    def __init__(self, file_id: str, speaker: str, path: str, framerate: int):

        self.path = os.path.normpath(path)
        self._length = None             # total length of audio
        self.segments_length = 0.0      # total length of annotated stm segments for this audio
        self.segments = []              # Stm segments
        self.file_id = file_id          # file id in Stm
        self.speaker = speaker
        self._audio_md5 = None

        self._framerate = framerate

        if self.file_id.count("-") != 1:
            raise ValueError(f"Bad FileId='{self.file_id}' For sorting to work well, we recommend that "
                             "FileID=SetID-File. -> Exactly one '-' character in file id/audio name expected")

        if not re.match(AnnotatedAudio.RE_FILE_ID, self.file_id):
            raise ValueError(f"Bad FileId='{self.file_id}' contains forbidden characters")

        if not re.match(AnnotatedAudio.RE_SPEAKER_ID, self.speaker):
            raise ValueError(f"Bad SpeakerId='{self.speaker}' contains forbidden characters")

        audio_path_name = os.path.splitext(os.path.basename(self.path))[0]
        if audio_path_name != self.file_id:
            raise ValueError(f"File id '{self.file_id}' doesn't correspond to real "
                             f"filename '{audio_path_name}' at path {self.path}. File id should be equal to name of "
                             f"wave file without the *.wav extension")

    def check(self, shallow=False):
        check_file(self.path)
        assert str(self.path).endswith(".wav")

        if not shallow:
            self.read_and_check_physical_file()
        else:
            # some insane number -> just to be able to check annotation without reading the file physically
            self._length = 999999999.9

        self.sort_segments()
        self.segments[0].check(self._length)
        # if the annotated audio contains multiple segments, check they do not overlap
        for prev_segment, segment in zip(self.segments, self.segments[1:]):
            segment.check(self._length)
            if prev_segment.end_time > segment.start_time:
                raise ValueError(f"Segments overlap! - '{prev_segment}' vs. '{segment}")

        if shallow:
            # remove insane number!
            self._length = None

    def get_words(self):
        """
        Returns set of all words that are contained in audio file's segments
        """
        words = set()
        for segment in self.segments:
            words.update(segment.get_words())
        return words

    def get_text_for_lm(self):
        """
        Returns list of text lines (~segments) stored in audio file's segments
        """
        text = list()
        for segment in self.segments:
            text.append(segment.get_text_for_lm())
        return text

    def get_text_for_am(self, dictionary_wordset):
        """
        @param dicionary_wordset Set containing all words from dictionary for word filtering
        Returns list of text lines (~segments) stored in audio file's segments
        """
        text = list()
        for segment in self.segments:
            text.append(segment.get_text_for_am(dictionary_wordset))
        return text

    def get_length(self):
        self.read_and_check_physical_file()
        return self._length

    def get_hash(self):
        self.read_and_check_physical_file()
        return self._audio_md5

    def add_segment(self, segment: AnnotationSegment):
        """
        Adds a segment that belongs to this audio file into database
        @param segment  general.objects.AnnotationSegment of this file
        """
        segment_length = segment.end_time - segment.start_time
        if segment_length > AnnotatedAudio._MAX_SEGMENT_LENGTH:
            _logger.warning(f"OMITTED: Segment {self.path} {segment.start_time}s-{segment.end_time}s is too long. Maximum segment length "
                            f"is {AnnotatedAudio._MAX_SEGMENT_LENGTH}")
            return
        self.segments.append(segment)
        self.segments_length += segment_length

    def sort_segments(self):
        self.segments.sort(key=lambda s: s.start_time)  # sort segments by start time

    def try_to_fix_segment_times(self, threshold=0.02, use_physical_files=False):
        self.sort_segments()
        for prev_segment, segment in zip(self.segments, self.segments[1:]):
            diff = prev_segment.end_time - segment.start_time
            if 0.0 < diff <= threshold:
                _logger.debug(f"Segments overlap! - '{prev_segment}' vs. '{segment}' - auto fixing")
                segment.start_time = prev_segment.end_time

        # truncate segments by the end of a physical file, discard segments past the end of a recording
        if use_physical_files:
            wav_length = self.get_length()
            fixed_segments = []
            for segment in self.segments:
                if segment.start_time >= wav_length:
                    _logger.warning(f"OMITTED: Segment {self.path} {segment.start_time}s-{segment.end_time}s is past the end of a "
                                    f"recording.")
                    continue
                if segment.end_time > wav_length:
                    _logger.debug(f"Segment end is bad! -{self.path} -> '{segment.end_time}s' -> '{wav_length}s' - auto fixing")
                    segment.end_time = wav_length
                fixed_segments.append(segment)
            self.segments = fixed_segments

    def read_and_check_physical_file(self):
        """
        Access the binary wav file, check number of channels and framerate, compute length and hash
        """
        if self._length is None:
            try:
                with wave.open(os.path.realpath(self.path), "rb") as iwave:
                    if iwave.getnchannels() != 1:
                        raise ValueError(f"Audio should have exactly one channel! File '{self.path}' "
                                         f"has {iwave.getnchannels()} channels")

                    if iwave.getframerate() != self._framerate:
                        raise ValueError(f"Audio should have framerate {self._framerate}! File '{self.path}' "
                                         f"has framerate {iwave.getframerate()}")

                    self._length = round(iwave.getnframes() / iwave.getframerate(), AnnotationSegment.rounding_ndigits)
                    self._audio_md5 = hashlib.md5(iwave.readframes(iwave.getnframes())).digest()
            except Exception as e:
                raise ValueError(f"Exception occured while reading physical data of '{self.path}': {e}")

    def get_voice_segmentation(self):
        return [f"{int(segment.start_time * VAD.HTK_TIME_MULTIPLICATION_CONSTANT)} "
                f"{int(segment.end_time * VAD.HTK_TIME_MULTIPLICATION_CONSTANT)} "
                f"{self.BSAPI_VOICE_LABEL}" for segment in self.segments
                if not segment.is_empty()]

    def get_grapheme_counts(self):
        grapheme_counts = Counter()
        for segment in self.segments:
            grapheme_counts += Counter(segment.get_grapheme_counts())

        return dict(grapheme_counts)

    def __eq__(self, other):
        # Equality operator for sorting while writing PhxAnnotation object
        return self.file_id == other.file_id

    def __lt__(self, other):
        # Less than operator for sorting while writing PhxAnnotation object
        return self.file_id < other.file_id
