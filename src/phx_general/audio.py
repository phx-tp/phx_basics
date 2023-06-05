"""
General utilities for working with audio files
"""

import contextlib
import wave


def get_wav_length(wav_file):
    with contextlib.closing(wave.open(wav_file, mode='rb')) as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())
