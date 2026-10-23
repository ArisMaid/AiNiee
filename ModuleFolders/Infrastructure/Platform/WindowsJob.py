"""Lifetime helper for one native Windows Job Object.

This module only manages a job handle and performs no process discovery,
name/PID termination, filesystem, network, or shell I/O. Callers own handles.
"""

import ctypes
import os
from ctypes import wintypes

HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t
LARGE_INTEGER = ctypes.c_longlong

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_MAX_HANDLE = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", LARGE_INTEGER),
        ("PerJobUserTimeLimit", LARGE_INTEGER),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ULONG_PTR),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


def _native_error(tag, operation, code):
    """Build an OSError carrying both a task tag and native error code."""
    message = f"{tag}: {operation} failed"
    if code:
        return OSError(code, f"{message} (Windows error {code})", None, code)
    return OSError(message)


class WindowsJob:
    """Owner of an unnamed, kill-on-close Windows Job Object.

    The caller must own every assigned process handle, create a child
    suspended, call :meth:`assign` while suspended, and only then resume it.
    This helper cannot verify suspension and never closes caller handles.
    Lifetime is explicit: there is no destructor; :meth:`close` kills members.
    """

    def __init__(self):
        if os.name != "nt":
            raise OSError("WINDOWS_JOB_UNAVAILABLE")

        self._handle = None
        kernel32 = self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._create_job_object = kernel32.CreateJobObjectW
        self._create_job_object.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._create_job_object.restype = HANDLE

        self._set_information_job_object = kernel32.SetInformationJobObject
        self._set_information_job_object.argtypes = (
            HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD)
        self._set_information_job_object.restype = wintypes.BOOL

        self._assign_process_to_job_object = kernel32.AssignProcessToJobObject
        self._assign_process_to_job_object.argtypes = [HANDLE, HANDLE]
        self._assign_process_to_job_object.restype = wintypes.BOOL

        self._terminate_job_object = kernel32.TerminateJobObject
        self._terminate_job_object.argtypes = [HANDLE, wintypes.UINT]
        self._terminate_job_object.restype = wintypes.BOOL

        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [HANDLE]
        self._close_handle.restype = wintypes.BOOL

        self._get_process_id = kernel32.GetProcessId
        self._get_process_id.argtypes = [HANDLE]
        self._get_process_id.restype = DWORD

        self._get_current_process_id = kernel32.GetCurrentProcessId
        self._get_current_process_id.argtypes = []
        self._get_current_process_id.restype = DWORD

        job = self._create_job_object(None, None)
        if not job:
            code = ctypes.get_last_error()
            raise _native_error("WINDOWS_JOB_CREATE", "CreateJobObjectW", code)

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = self._set_information_job_object(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
            ctypes.sizeof(info))
        if not configured:
            code = ctypes.get_last_error()
            self._close_handle(job)
            raise _native_error(
                "WINDOWS_JOB_CONFIGURE", "SetInformationJobObject", code)

        self._handle = job

    @property
    def handle(self):
        """Return the owned native job handle, or raise after close."""
        return self._require_open()

    def _require_open(self):
        if self._handle is None:
            raise RuntimeError("WINDOWS_JOB_CLOSED")
        return self._handle

    def assign(self, process_handle):
        """Add a caller-owned, suspended child process to this job.

        ``process_handle`` must be a positive native handle value. Keep it open
        and resume the child only after successful assignment; this helper
        never closes it. Attach only a caller-created, owned process; unrelated
        processes are not safe to attach.
        """
        job = self._require_open()
        if (
            isinstance(process_handle, bool)
            or not isinstance(process_handle, int)
            or process_handle <= 0
            or process_handle > _MAX_HANDLE
        ):
            raise ValueError("WINDOWS_JOB_INVALID_HANDLE")

        native_process = HANDLE(process_handle)
        pid = self._get_process_id(native_process)
        if not pid:
            code = ctypes.get_last_error()
            raise _native_error(
                "WINDOWS_JOB_ASSIGN_GET_PROCESS_ID", "GetProcessId", code)
        if pid == self._get_current_process_id():
            raise ValueError("WINDOWS_JOB_SELF_ASSIGN")
        if not self._assign_process_to_job_object(job, native_process):
            code = ctypes.get_last_error()
            raise _native_error(
                "WINDOWS_JOB_ASSIGN_PROCESS", "AssignProcessToJobObject", code)

    def terminate(self, exit_code=1):
        """Terminate all processes in this job with ``exit_code``."""
        job = self._require_open()
        if (
            isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code < 0
            or exit_code > 0xFFFFFFFF
        ):
            raise ValueError("WINDOWS_JOB_INVALID_EXIT_CODE")
        if not self._terminate_job_object(job, exit_code):
            code = ctypes.get_last_error()
            raise _native_error(
                "WINDOWS_JOB_TERMINATE", "TerminateJobObject", code)

    def close(self):
        """Close the owned job handle once; closing live jobs kills members."""
        job = self._handle
        if job is None:
            return
        self._handle = None
        if not self._close_handle(job):
            code = ctypes.get_last_error()
            raise _native_error("WINDOWS_JOB_CLOSE", "CloseHandle", code)

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
