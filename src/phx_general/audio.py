"""
General utilities for working with audio files
"""

import contextlib
import wave
import subprocess
import re
import sys

from phx_general.file import check_file


def get_wav_length(path):
    """
    Returns length of audio file in seconds.

    :param path: (str) path to the audio file
    :return: duration of the audio file as float number, measured in seconds.
    """

    assert path, 'path argument is empty'
    check_file(path)
    
    try:
        with contextlib.closing(wave.open(path, mode='rb')) as wav_file:
            return wav_file.getnframes() / float(wav_file.getframerate())    
    except Exception as exc:
        if not (exc and str(exc) and re.match('.*unknown format.*', str(exc).lower(), re.DOTALL)):
            raise exc
        else:
            # unsupported format - try sox
            cmd = ['sox', path, '-n', 'stat']
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
            (bstdoutdata, bstderrdata) = proc.communicate()
            stdoutdata = bstdoutdata.decode(sys.getdefaultencoding())
            stderrdata = bstderrdata.decode(sys.getdefaultencoding())
            assert proc.returncode == 0, \
                'Failed with returncode=%(returncode)s, stdout="%(stdoutdata)s", stderr="%(stderrdata)s"' \
                % dict(returncode=proc.returncode, stdoutdata=stdoutdata, stderrdata=stderrdata)
            regex_time = re.compile('.*Length \\(seconds\\): *([0-9.]+).*', re.DOTALL)
            assert regex_time.match(stderrdata), 'Invalid stderrdata "%(stderrdata)s"' % {'stderrdata': stderrdata}
            return float(regex_time.sub('\\1', stderrdata))
