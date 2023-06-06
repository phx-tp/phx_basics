import multiprocessing
import os
from multiprocessing import Process
from tempfile import TemporaryDirectory
from typing import Iterable

from typeguard import typechecked

from phx_general.audio import get_wav_length
from phx_general.bsapi.bsapi_license import BSAPILicense
from phx_general.bsapi.defaults import PHXBinaries
from phx_general.file import check_file, file2list, list2file
from phx_general.shell import shell
from phx_general.type import path_type


@typechecked
class Segmentation:
    def __init__(self):
        """
        Dictionary {'abs_file_path': [(start, end), ...]} with entry fro each *.wav found in directory's tree
        Maps filename to list of tuples [(start_sec, end_sec), ] for voice segments in file
        """
        self._data = dict()
        
    def __getitem__(self, name):
        return self._data[name]

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def add_segements(self, real_path: path_type, voice_segments: Iterable[tuple[float]]):
        check_file(real_path)
        for seg in voice_segments:
            if len(seg) != 2:
                raise ValueError("Segmentation tuple should have 2 elements - start and end; both float numbers")

        self._data[real_path] = voice_segments

    def merge(self, other):
        for k in other.keys():
            if k in self._data:
                raise ValueError(f"Cannot merge segmentations, contain duplicate audio path '{k}'")
            self._data[k] = other[k]

    def add_segfile(self, audio_path, bsapi_segfile):
        seg_lines = file2list(bsapi_segfile)
        voice_segments = []
        for l in seg_lines:
            chunks = l.split()
            if chunks[2] == 'voice':
                start = float(chunks[0]) / VAD.HTK_TIME_MULTIPLICATION_CONSTANT
                end = float(chunks[1]) / VAD.HTK_TIME_MULTIPLICATION_CONSTANT
                voice_segments.append((start, end))

        self.add_segements(audio_path, voice_segments)

    def get_length(self):
        """ Returns net speech in segments in seconds"""
        return sum(self._get_net_speech4audio(path) for path in self._data)

    def _get_net_speech4audio(self, path):
        return sum((segment[1] - segment[0]) for segment in self._data[path])

    def get_net_speech_per_audio(self):
        return {path: self._get_net_speech4audio(path) for path in self._data}


class VAD:

    HTK_TIME_MULTIPLICATION_CONSTANT = 10000000.0
    DEFAULT_VAD_CFG = "/media/marvin/_projects/VAD/models/2.3.0/vad_stt.bs"
    BSAPI_COMMAND = "vad"

    def __init__(self, phxcmd_bin, vad_cfg=None, bsapi_license=None):
        """
        Class for segmenting audio files
        @param phxcmd_bin BSAPI phxcmd binary
        @param vad_cfg VAD configuration - path to bsapi *.bs file - can be None
        """
        check_file(phxcmd_bin)
        self.phxcmd_bin = phxcmd_bin
        if vad_cfg:
            check_file(vad_cfg)
            self._vad_cfg = vad_cfg  # path to vad *.bs file
        else:
            # use default path
            self._vad_cfg = VAD.DEFAULT_VAD_CFG

        self.delimiter = "\t"
        self._license = bsapi_license   # path to bsapi license file

    def process_file(self, filename, create_seg_file: bool = False):
        """
        Process one *.wav file by BSAPI VAD
        @param dirname Root directory where to start searching for *.wav files
        @param create_seg_file If true, *.seg segmentation file is created next to every *.wav file found in dirname
        @return Segmentation object, where Segmentation.data is dict {'abs_file_path': [(start_sec, end_sec), ...]}
                Maps filename to list of tuples [(start, end), ] for voice segments in file
        """
        return self._process(os.path.dirname(filename), [os.path.basename(filename)], create_seg_file, None)

    def process_files(self, filenames, create_seg_files: bool = False, num_processes=multiprocessing.cpu_count()):
        """
        Process multiple *.wav files by BSAPI VAD
        @param filenames Filenames/paths to be processed by vad
        @param create_seg_files If true, *.seg segmentation file is created next to every *.wav file among filenames
        @param num_processes Number of parallel processes to run VAD in defaults to number of cores on computer
        @return Segmentation object, where Segmentation.data is dict {'abs_file_path': [(start_sec, end_sec), ...]}
                Maps filename to list of tuples [(start, end), ] for voice segments in file
        """
        paths = [os.path.normpath(os.path.realpath(f)).lstrip("/") for f in filenames]
        return self._process_parallel("/", paths, create_seg_files, num_processes)

    def process_directory(self, dirname, create_seg_files: bool = False, num_processes=multiprocessing.cpu_count()):
        """
        Process all *.wav files in directory and all of it's sub-directories by BSAPI VAD in parallel manner
        @param dirname Root directory where to start searching for *.wav files
        @param create_seg_files If true, *.seg segmentation file is created next to every *.wav file found in dirname
        @param num_processes Number of parallel processes to run VAD in defaults to number of cores on computer
        @return Dictionary {'abs_file_path': [(start, end), ...]} with entry fro each *.wav found in directory's tree
                Maps filename to list of tuples [(start_sec, end_sec), ] for voice segments in file
        """
        paths = []
        dirname = os.path.abspath(dirname)
        for root, dirs, files in os.walk(dirname):
            for file in files:
                if file.endswith(".wav"):
                    rel_root = os.path.relpath(root, start=dirname)
                    paths.append(os.path.normpath(os.path.join(rel_root, file)))

        return self._process_parallel(dirname, paths, create_seg_files, num_processes)

    def _process_parallel(self, dirname, paths, create_seg_files, num_processes):
        processes = []
        # do not run more VAD processes than the number of slots
        if self._license:
            num_processes = min(num_processes, BSAPILicense(self._license).get_number_of_slots('VAD-tech'))
        chunk_size = int((len(paths) + num_processes - 1) / num_processes)
        queue = multiprocessing.SimpleQueue()
        for n, data in enumerate([paths[x:x+chunk_size] for x in range(0, len(paths), chunk_size)]):
            p = Process(target=self._process, args=(dirname, data, create_seg_files, queue))
            processes.append(p)
            p.start()

        result = Segmentation()
        for _ in processes:
            segmentation = queue.get()
            result.merge(segmentation)

        for p in processes:
            p.join()

        return result

    def _process(self, dirname, paths, create_seg_files, queue=None):
        segmentation = Segmentation()
        with TemporaryDirectory() as tmp_dir:
            realpaths_list = [os.path.join(dirname, p) for p in paths]
            if create_seg_files:
                paths_list = realpaths_list
            else:
                paths_list = []
                # create symlinks so that vad binary can create *.seg files, along them - they will be then discarded
                for p in paths:
                    tmp_pathname = os.path.join(tmp_dir, p)
                    os.makedirs(os.path.dirname(tmp_pathname), exist_ok=True)
                    os.symlink(os.path.join(dirname, p), tmp_pathname)
                    paths_list.append(tmp_pathname)

            for p in paths_list:
                check_file(p)
            tmp_filelist = os.path.join(tmp_dir, "list")
            list2file(paths_list, tmp_filelist)
            cmd = [self.phxcmd_bin, VAD.BSAPI_COMMAND, "-c", self._vad_cfg, "-l", tmp_filelist]
            if self._license:
                cmd.extend(["-L", self._license])
            shell(cmd)

            for real_path, tmp_path in zip(realpaths_list, paths_list):
                bsapi_segfile = f"{os.path.splitext(tmp_path)[0]}.seg"
                segmentation.add_segfile(real_path, bsapi_segfile)

        if queue:
            queue.put(segmentation)

        return segmentation

    def get_net_speech_per_audio(self, paths):
        return self.process_files(paths).get_net_speech_per_audio()


def calculate_net_speech(audio_list,
                         phxcmd_binary=PHXBinaries.BSAPI,
                         vad_config=VAD.DEFAULT_VAD_CFG,
                         multiprocessing: bool = False):
    vad = VAD(phxcmd_bin=phxcmd_binary, vad_cfg=vad_config)
    vad_segmentation = Segmentation()
    if multiprocessing:
        vad_segmentation.merge(vad.process_files(audio_list))
    else:
        for audio in audio_list:
            if audio not in vad_segmentation.keys():
                vad_segmentation.merge(vad.process_file(audio))
    return vad_segmentation.get_length()



