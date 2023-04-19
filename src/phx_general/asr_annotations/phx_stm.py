import logging
import os
import re

from general.file import list2file
from general.objects.annotated_audio import AnnotatedAudio
from general.objects.annotation_segment import AnnotationSegment
from general.objects.phx_annotation import PhxAnnotation

_logger = logging.getLogger(__name__)


class PhxStm(PhxAnnotation):

    def get_name(self):
        return 'PhxStm'

    @classmethod
    def get_source_file_name(cls):
        return 'stt.phxstm'

    def write_as_kaldi_files(self, directory, dictionary=None):
        """
        Writes kaldi prepared files into specified directory
        Creates directory if it doesn't exist already
        """
        os.makedirs(directory, exist_ok=True)

        outputs = {'text': [], 'wav.scp': [], 'segments': [], 'reco2file_and_channel': [], 'utt2spk': [],
                   'wav2dur': [], 'wordcnts': [], 'spk2utt': []}
        wordcnt_dict = dict()
        spk2utt_dict = dict()

        dictionary_wordset = None
        if dictionary:
            dictionary_wordset = dictionary.get_words()

        for af in self._annotated_audio.values():
            recording_id = af.file_id + "-A"
            speaker_id = PhxAnnotation._get_speaker_id(recording_id, af.speaker)
            for segment in af.segments:
                utterance_id = PhxAnnotation._get_utterance_id(recording_id, af.speaker, segment.start_time, segment.end_time)
                # count word occurences
                segment_text = segment.get_text_for_am(dictionary_wordset)
                for w in segment_text.split():
                    if w not in wordcnt_dict:
                        wordcnt_dict[w] = 0
                    wordcnt_dict[w] += 1

                outputs['text'].append(f"{utterance_id} {segment_text}")
                outputs['segments'].append(f"{utterance_id} {recording_id} {segment.start_time} {segment.end_time}")
                outputs['utt2spk'].append(f"{utterance_id} {speaker_id}")
                if speaker_id not in spk2utt_dict:
                    spk2utt_dict[speaker_id] = []
                spk2utt_dict[speaker_id].append(utterance_id)

            outputs['reco2file_and_channel'].append(f"{recording_id} {af.file_id} A")
            outputs['wav2dur'].append(f"{af.path} {af.get_length()}")
            outputs['wav.scp'].append(f"{recording_id} {af.path}")  # no sox re-processing or anything

        outputs['wordcnts'] = [f"{w}\t{c}" for (w, c) in wordcnt_dict.items()]
        outputs['spk2utt'] = [f"{spk} {' '.join(utts)}" for (spk, utts) in spk2utt_dict.items()]

        for out, lines in outputs.items():
            out_filename = os.path.join(directory, out)
            list2file(out_filename, sorted(lines))

    def load_from_kaldi_files(self, directory, is_train):
        """
        Converts kaldi-prepared files to a phx stm
        """
        self._reset()
        self.is_train = is_train
        with open(os.path.join(directory, 'wav.scp'), 'r') as wavscp:
            for line in wavscp:
                if not re.match("^.*-A .*\.wav$", line):
                    raise ValueError("Kaldi files doesn't seem to be prepared by PhxStm class - can't load them")
                recording_id, audiopath = line.split()
                file_id = recording_id.rstrip('A').rstrip('-')  # removes trailing -A
                self._annotated_audio[audiopath] = AnnotatedAudio(file_id, 'unknown', audiopath, self._framerate)

        with open(os.path.join(directory, 'text'), 'r') as text:
            for line in text:
                try:
                    utterance_id = line.split()[0]
                    recording_id, speaker, start, end = PhxStm._split_utterance_id(utterance_id)
                    file_id = recording_id.rstrip('A').rstrip('-')  # removes trailing -A channel
                    words = line.split()[1:]
                    annotated_audio = self.get_annotated_audio_by_file_id(file_id)
                    annotated_audio.speaker = speaker
                    annotated_audio.add_segment(AnnotationSegment(start, end, words))
                except Exception as e:
                    raise ValueError(f"Kaldi files doesn't seem to be prepared by PhxStm class - "
                                     f"can't load them - eror parsing utterance_id: {e}")

