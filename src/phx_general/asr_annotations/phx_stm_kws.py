import logging

from general.file import file2list
from general.objects.annotated_audio import AnnotatedAudio
from general.objects.annotation_segment import AnnotationSegment
from general.objects.phx_annotation import PhxAnnotation
from general.objects.phx_stm import PhxStm
from general.objects.vad import VAD
from general import checking as asrchk

_logger = logging.getLogger(__name__)


class PhxStmKWS(PhxAnnotation):

    MLF_HEADER = "#!MLF!#"
    MLF_SEPARATOR = "."

    def get_name(self):
        return 'PhxStmKWS'

    def get_source_file_name(self):
        return 'kws.phxstm'

    def check(self, expected_graphemes=None, permissive=False, shallow=False):
        super(PhxStmKWS, self).check(expected_graphemes, permissive, shallow)

        for annotated_audio in self._annotated_audio.values():
            for segment in annotated_audio.segments:
                if len(segment.get_words()) > 1:
                    raise ValueError(f"Each segment of PhxStmKWS should be one word only. {len(segment.get_words)} words"
                                     f" found in segment '{segment.get_text()}' of audio file '{annotated_audio.path}'")

    def add_annotations_from_ctm_and_phx_stm(self, ctm, phx_stm_dir):
        asrchk.check_file_access(ctm, mode='r')
        phx_stm = PhxStm(phx_stm_dir, is_train=self.is_train, override_audio_paths=self._override_audio_paths)

        aa = None
        last_file_id = None
        for line in file2list(ctm):
            file_id, channel, start, duration, word = line.split()
            if file_id != last_file_id:  # search for appropriate annotated audio only in case of change in file_id
                aa = phx_stm.get_annotated_audio_by_file_id(file_id)
                last_file_id = file_id
            if not aa:
                continue
            if aa.path not in self._annotated_audio:
                self._annotated_audio[aa.path] = AnnotatedAudio(file_id, aa.speaker, aa.path, self._framerate)

            fstart = round(float(start), 5)
            fend = round(fstart + float(duration), 5)
            self._annotated_audio[aa.path].add_segment(AnnotationSegment(fstart, fend, [word]))

    def write_as_mlf(self, mlf):
        if self.empty():
            _logger.warning("Creating EMPTY MLF - that's probably not what you want to do!")

        with open(mlf, 'w') as out_mlf:
            out_mlf.write(f"{PhxStmKWS.MLF_HEADER}\n")
            for annotated_audio in sorted(self._annotated_audio.values()):
                out_mlf.write(f'"{annotated_audio.path.replace(".wav", ".lab")}"\n')

                last_segment_end = 0
                annotated_audio.sort_segments()
                for segment in annotated_audio.segments:
                    segment_start = int(segment.start_time * VAD.HTK_TIME_MULTIPLICATION_CONSTANT)
                    segment_end = int(segment.end_time * VAD.HTK_TIME_MULTIPLICATION_CONSTANT)
                    # beware of comparing float values exactly
                    if segment.start_time - last_segment_end > 0:
                        out_mlf.write(f"{last_segment_end} {segment_start} _NO_ALIGN_SEGMENT_\n")

                    out_mlf.write(f'{segment_start} {segment_end} {segment.get_text_for_scoring()}\n')

                    last_segment_end = segment_end

                annotated_audio_end = int(annotated_audio.get_length() * VAD.HTK_TIME_MULTIPLICATION_CONSTANT)
                if annotated_audio_end - last_segment_end > 0:
                    out_mlf.write(f"{last_segment_end} {annotated_audio_end} _NO_ALIGN_SEGMENT_\n")

                out_mlf.write(f"{PhxStmKWS.MLF_SEPARATOR}\n")
