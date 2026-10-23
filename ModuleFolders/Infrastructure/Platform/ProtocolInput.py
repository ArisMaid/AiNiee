"""Bounded, non-blocking protocol input for the worker subprocess.

The parent keeps a framed worker's stdin open so it can send a cancel frame.
A thread blocked in ``sys.stdin.buffer.readline`` or ``os.read`` can prevent
native extension imports from completing on Windows, so anonymous pipes are
polled with ``PeekNamedPipe`` and ``os.read`` is issued only when bytes are
already available.  One reader is used sequentially: first for the request and
later on the controller thread for cancellation.  A persistent byte buffer
keeps any bytes that arrived in the same pipe read after the returned message.

The wrapped stream is borrowed and is never closed.  Non-Windows streams, and
Windows handles that are not pipes, use the stream's bounded binary
``read``/``readline`` methods.  Callers must provide a positive size.
"""

import ctypes
import os
import time

_CHUNK = 65536
_POLL = .01
_FILE_TYPE_UNKNOWN = 0
_FILE_TYPE_PIPE = 3
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232

_pipe_api = None


def _kernel32():
    """Return kernel32 once with pointer-width-correct pipe signatures."""
    global _pipe_api
    if _pipe_api is None:
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetFileType.argtypes = [wintypes.HANDLE]
        api.GetFileType.restype = wintypes.DWORD
        api.PeekNamedPipe.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        api.PeekNamedPipe.restype = wintypes.BOOL
        _pipe_api = api
    return _pipe_api


def _size(size):
    """Validate the required positive, bounded read size."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError('WORKER_INPUT_SIZE_INVALID')
    return size


class ProtocolInput:
    """Sequential bounded reader for one framed worker input channel.

    Calls must be sequential; this reader makes no thread-safety promise.
    """

    def __init__(self, stream):
        self._stream = stream
        self._buffer = bytearray()
        self._eof = False
        self._fd = None
        self._handle = None
        self._api = None
        self._dword = None
        self._open_pipe()

    def _open_pipe(self):
        """Use non-blocking reads when stdin is a Windows pipe."""
        if os.name != 'nt':
            return
        try:
            import msvcrt
            fd = self._stream.fileno()
            handle = msvcrt.get_osfhandle(fd)
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            return
        if handle == -1:
            return
        api = _kernel32()
        ctypes.set_last_error(0)
        file_type = api.GetFileType(handle)
        if file_type == _FILE_TYPE_PIPE:
            from ctypes import wintypes
            self._fd = fd
            self._handle = handle
            self._api = api
            self._dword = wintypes.DWORD
            return
        if file_type == _FILE_TYPE_UNKNOWN:
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error) from None

    def _peek(self):
        """Return bytes available in the pipe, or None at EOF."""
        available = self._dword()
        ctypes.set_last_error(0)
        if not self._api.PeekNamedPipe(
                self._handle, None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                return None
            raise ctypes.WinError(error) from None
        return available.value

    def _read_pipe(self, capacity):
        """Return pipe bytes, b'' at EOF, or None when no bytes are ready."""
        available = self._peek()
        if available is None:
            return b''
        if available == 0:
            time.sleep(_POLL)
            return None
        try:
            return os.read(self._fd, min(available, capacity, _CHUNK))
        except OSError as error:
            if getattr(error, 'winerror', None) in (
                    _ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                return b''
            raise

    def _pump(self, limit, line):
        """Make one bounded read attempt into the persistent buffer."""
        need = limit - len(self._buffer)
        if self._fd is None:
            chunk = (self._stream.readline(need) if line
                     else self._stream.read(need))
        else:
            chunk = self._read_pipe(need)
            if chunk is None:
                return
        if not chunk:
            self._eof = True
            return
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError('WORKER_INPUT_BINARY_REQUIRED')
        self._buffer.extend(chunk)

    def _take(self, count):
        if count <= 0:
            return b''
        data = bytes(self._buffer[:count])
        del self._buffer[:count]
        return data

    def read(self, size):
        """Return exactly ``size`` bytes, or the EOF remainder."""
        limit = _size(size)
        while len(self._buffer) < limit and not self._eof:
            self._pump(limit, False)
        return self._take(min(len(self._buffer), limit))

    def readline(self, size):
        """Return one line including its newline, at most ``size`` bytes."""
        limit = _size(size)
        while True:
            newline = self._buffer.find(b'\n', 0, limit)
            if newline >= 0:
                return self._take(newline + 1)
            if len(self._buffer) >= limit or self._eof:
                return self._take(min(len(self._buffer), limit))
            self._pump(limit, True)
