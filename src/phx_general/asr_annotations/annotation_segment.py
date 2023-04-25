import re

from collections import Counter
from typing import Union

from phx_general.asr_annotations.phx_annotation_tags import PhxAnnotationTags
from phx_general.sequences import TimeSequenceItem
from typeguard import typechecked

from phx_general.asr_dictionary.dictionary import Dictionary


class AnnotationSegment(TimeSequenceItem):
    EMPTY = ["<empty>"]
    rounding_ndigits = 2

    @typechecked
    def __init__(self, start: float, end: float, words: list[str]):
        self.start_time = start
        self.end_time = end
        self._words = words

    @property
    def start_time(self):
        return self._start_time

    @start_time.setter
    def start_time(self, value):
        self._start_time = round(value, self.rounding_ndigits)

    @property
    def end_time(self):
        return self._end

    @end_time.setter
    def end_time(self, value):
        self._end = round(value, self.rounding_ndigits)

    @property
    def length(self):
        return self.end_time - self.start_time

    @typechecked
    def check(self, audio_length: float):
        if self.start_time >= self.end_time:
            raise ValueError(f"Segment start >= end - {self.start_time} >= {self.end_time}. "
                             "Either bad segment boundaries or an unnecessary empty segment")

        if self.start_time >= audio_length:
            raise ValueError(f"Segment start (at {self.start_time}) seems to be past the end of the recording "
                             f"(recording length: {audio_length})")

        # segment times should be rounded to 2 decimal places ->  ~ 0.01 / 2 is our tolerance
        if self.end_time - audio_length > 0.0051:
            raise ValueError(f"Segment end (at {self.end_time}) seems to be past the end of the recording "
                             f"(recording length: {audio_length})")

        if self._words == AnnotationSegment.EMPTY:
            raise ValueError("Empty segment")

        for w in self._words:
            if re.match("\[.*\]", w):
                continue

            if not w:
                raise ValueError(f"Empty word among tokens - maybe two spaces instead of one?")

            if w.lower() != w:
                raise ValueError(f"Word '{w}' in annotation is not lowercase!")

    @typechecked
    def get_words(self):
        """
        Returns set of all words that are contained in segment
        """
        return set(self._words)

    @typechecked
    def get_text(self, clean_tags=False):
        """
        Returns string - text line (~segments) stored in segment
        """
        if clean_tags:
            return " ".join(PhxAnnotationTags.delete_tags_from_iterable(self._words))
        else:
            return " ".join(self._words)

    def get_words_for_am(self, dictionary_wordset=None):
        """
        Returns set of all words that are contained in segment
        """
        return set(self._words_by_dictionary(dictionary_wordset))

    def get_words_for_lm(self):
        """
        Returns set of all words that are contained in segment
        """
        return set(self._words_by_dictionary(dictionary_wordset=None))

    def get_text_for_am(self, dictionary_wordset=None):
        """
        @param dicionary_wordset Set containing all words from dictionary for word filtering
        Returns string - text line (~segments) stored in segment
        """
        return " ".join(self._words_by_dictionary(dictionary_wordset))

    def get_text_for_lm(self):
        """
        Returns string - text line (~segments) stored in segment
        """
        return " ".join(self._words_by_dictionary(dictionary_wordset=None, map_spelling=True))

    def get_text_for_scoring(self, map_spelling=True):
        """
        Returns string - text line (~segments) stored in segment
        """
        return " ".join(self._words_by_dictionary(dictionary_wordset=None, map_spelling=map_spelling))

    def __str__(self):
        return f"Segment {self.start_time}-{self.end_time}: '{self.get_text()}'"

    def is_empty(self):
        return self._words == self.EMPTY

    def get_grapheme_counts(self):
        grapheme_counts = Counter(default_value=0)
        for w in self._words:
            for g in w:
                grapheme_counts[g] += 1
        return dict(grapheme_counts)

    @typechecked
    def _words_by_dictionary(self, dictionary_wordset: Union[set, None] = None, map_spelling=False):

        words = []
        for w in self._words:
            if re.match("\[.*\]", w):
                w = w.strip("[]").lower()
                if dictionary_wordset and w not in dictionary_wordset:
                    words.append("<unk>")
                    continue

            if map_spelling and Dictionary.is_spelling(w):
                w = w.rstrip('_')

            words.append(w)

        return words
