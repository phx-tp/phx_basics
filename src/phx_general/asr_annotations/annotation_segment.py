import re

from general import checking as asrchk
from general.objects.dictionary import Dictionary
from collections import Counter

from general.objects.phx_annotation_tags import PhxAnnotationTags
from general.sequences import TimeSequenceItem


class AnnotationSegment(TimeSequenceItem):

    EMPTY = ["<empty>"]
    rounding_ndigits = 2

    def __init__(self, start, end, words):
        asrchk.check_arg_type("start", start, float, can_be_none=False)
        asrchk.check_arg_type("end", end, float, can_be_none=False)
        asrchk.check_arg_type('words', words, list, can_be_none=False)  # prevents words to be single string
        asrchk.check_arg_iterable('words', words, expected_elements_type=str, can_be_empty=False)
        self.start_time = start
        self.end_time = end
        self._words = words

    @property
    def start_time(self):
        return self._start

    @start_time.setter
    def start_time(self, value):
        self._start = round(value, self.rounding_ndigits)

    @property
    def end_time(self):
        return self._end

    @end_time.setter
    def end_time(self, value):
        self._end = round(value, self.rounding_ndigits)

    def check(self, audio_length):
        asrchk.check_arg_type("audio_length", audio_length, float, can_be_none=False)

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

    def get_words(self):
        """
        Returns set of all words that are contained in segment
        """
        return set(self._words)

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

    def _words_by_dictionary(self, dictionary_wordset=None, map_spelling=False):
        asrchk.check_arg_type('dictionary_wordset', dictionary_wordset, set, can_be_none=True)

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
