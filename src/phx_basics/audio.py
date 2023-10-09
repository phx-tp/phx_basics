"""
General utilities for working with audio files
"""

import contextlib
import wave


def get_wav_length(wav_file):
    with contextlib.closing(wave.open(wav_file, mode='rb')) as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())


def calculate_audio_full_length(audio_list):
    sum_audio_length = 0
    for audio in audio_list:
        sum_audio_length += get_wav_length(audio)
    return sum_audio_length