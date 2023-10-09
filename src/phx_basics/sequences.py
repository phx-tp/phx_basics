from __future__ import annotations
import abc
import math
from abc import ABC
from typing import Iterable


class TimeSequenceItem(ABC):
    @property
    @abc.abstractmethod
    def start_time(self):
        pass

    @property
    @abc.abstractmethod
    def end_time(self):
        pass

    def check_time_consistency(self, allow_zero_length: bool = False):
        if allow_zero_length:
            assert self.start_time <= self.end_time
        else:
            assert self.start_time < self.end_time

    def before(self, item: TimeSequenceItem, tolerance: float = 0):
        """
        Return bool if item is before 'self' with tolerance
        """
        return item.end_time < self.start_time - tolerance  # and item.start_time < self.start_time + tolerance

    def after(self, item: TimeSequenceItem, tolerance: float = 0):
        """
        Return bool if item is after 'self' with tolerance
        """
        return item.start_time > self.end_time + tolerance  # item.end_time > self.end_time - tolerance and


class FinalTimeSequenceItem(TimeSequenceItem):
    @property
    def start_time(self):
        return math.inf

    @property
    def end_time(self):
        return math.inf


class NextSegment(ValueError):
    pass


class TimeSequencesAlignment:
    def __init__(self, sequence1: Iterable[TimeSequenceItem], sequence2: Iterable[TimeSequenceItem]):
        assert len(list(sequence1)) == 0 or isinstance(list(sequence1)[0], TimeSequenceItem)
        assert len(list(sequence2)) == 0 or isinstance(list(sequence2)[0], TimeSequenceItem)
        self._sequence1 = sequence1
        self._sequence2 = sequence2

    def get_seq1len_alignment(self, tolerance: float = 0.1):
        """
        Return two sequences long as sequence1. Delete items from seq2 if they are out of seq1 segments.
        WARNING: If two sequences are tightly next to ech other the word on border of two segments have tendency to fit
        into next segment
        """
        seq1iter = iter(self._sequence1)
        next_seq1iter_helper = iter(list(self._sequence1)[1:] + [FinalTimeSequenceItem()])
        seq2iter = iter(self._sequence2)
        output_sequences = list()
        try:
            item2 = next(seq2iter)
            for item1, next_item1 in zip(seq1iter, next_seq1iter_helper):
                output_sequences.append([item1, list()])
                while item1.before(item2, tolerance):
                    # if item2.after(item1):  # item2 is inside item1
                    #     output_sequences[-1][1].append(item2)  # add item2 to output sequence
                    item2 = next(seq2iter)
                try:
                    while not item1.after(item2, tolerance):
                        if not next_item1.before(item2):
                            raise NextSegment()
                        output_sequences[-1][1].append(item2)  # add item2 to output sequence
                        item2 = next(seq2iter)
                except NextSegment:
                    continue

        except StopIteration:
            # add all from seq1 to output if seq2 is shorter
            for item1 in seq1iter:
                output_sequences.append([item1, list()])
        assert len(list(self._sequence1)) == len(output_sequences), f"{len(list(self._sequence1))} :: {len(output_sequences)}"
        return output_sequences
