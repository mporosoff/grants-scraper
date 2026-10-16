"""Read authenticated job logs as bounded bytes without rendering controls.

Recent gh versions guard non-JSON output even when stdout is a pipe. The
opt-in below applies only to this byte transport; callers still authenticate
the job metadata before using its historical log as evidence.
"""
from functools import lru_cache
import re
import subprocess
import threading


MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_HELP_BYTES = 256 * 1024
MAX_ERROR_BYTES = 64 * 1024
TIMEOUT_SECONDS = 60
_CHUNK_BYTES = 64 * 1024


class JobLogReadError(RuntimeError):
    """A safe transport error containing no captured command output."""


def _capture(command, limit, purpose):
    buffers = [bytearray(), bytearray()]
    failures = []
    lock = threading.Lock()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise JobLogReadError(f'GitHub job log {purpose} could not start') from None

    def fail(reason):
        with lock:
            if not failures:
                failures.append(reason)
        try:
            process.kill()
        except OSError:
            pass

    def drain(stream, buffer, maximum):
        try:
            while chunk := stream.read1(_CHUNK_BYTES):
                if len(buffer) + len(chunk) > maximum:
                    fail('exceeded its byte limit')
                    return
                buffer.extend(chunk)
        except OSError:
            fail('could not read captured output')
        finally:
            try:
                stream.close()
            except OSError:
                fail('could not finish reading captured output')

    readers = [threading.Thread(target=drain, args=(stream, buffer, maximum),
                                name=f'github-job-log-{number}', daemon=True)
               for number, (stream, buffer, maximum) in enumerate(
                   ((process.stdout, buffers[0], limit), (process.stderr, buffers[1], MAX_ERROR_BYTES)))]
    try:
        for reader in readers:
            reader.start()
        try:
            returncode = process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            fail('timed out')
            returncode = process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
        if any(reader.is_alive() for reader in readers):
            fail('could not finish reading captured output')
        if failures:
            raise JobLogReadError(f'GitHub job log {purpose} {failures[0]}')
        if returncode:
            raise JobLogReadError(f'GitHub job log {purpose} failed')
        return bytes(buffers[0])
    except (OSError, subprocess.TimeoutExpired):
        fail('could not finish')
        raise JobLogReadError(f'GitHub job log {purpose} could not finish') from None
    finally:
        # A descendant holding a pipe open must not block this caller in
        # close(). Its bounded daemon drain owns that pipe until EOF instead.
        for reader, stream in zip(readers, (process.stdout, process.stderr)):
            if not reader.is_alive():
                try:
                    stream.close()
                except OSError:
                    pass


@lru_cache(maxsize=1)
def _supports_escape_flag():
    help_bytes = _capture(['gh', 'api', '--help'], MAX_HELP_BYTES, 'capability check')
    return re.search(rb'(?m)^[ \t]*--allow-escape-sequences(?=[ \t]|$)', help_bytes) is not None


def read_job_log(repository, job_id):
    """Return raw bytes from one exact repository/job route, never terminal text."""
    if (not isinstance(repository, str)
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repository) is None
            or repository.split('/')[1] in ('.', '..')):
        raise ValueError('Invalid GitHub job log repository')
    if (isinstance(job_id, bool) or not isinstance(job_id, (str, int))
            or re.fullmatch(r'[1-9][0-9]{0,19}', str(job_id)) is None):
        raise ValueError('Invalid GitHub job log identifier')
    command = ['gh', 'api', f'repos/{repository}/actions/jobs/{job_id}/logs']
    if _supports_escape_flag():
        command.append('--allow-escape-sequences')
    return _capture(command, MAX_LOG_BYTES, 'retrieval')
