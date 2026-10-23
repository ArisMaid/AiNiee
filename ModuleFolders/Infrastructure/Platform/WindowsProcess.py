"""Native suspended-process startup owned by one Windows job.

This module is intentionally limited to native plumbing.  It creates a single
process, its standard pipes and job membership; it does not implement an
adapter, choose commands, perform shell expansion, or discover processes.
"""

import ctypes
import math
import numbers
import os
import subprocess
from ctypes import wintypes

HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
BOOL = wintypes.BOOL
SIZE_T = ctypes.c_size_t
DWORD_PTR = ctypes.c_size_t
LPVOID = ctypes.c_void_p
LPWSTR = wintypes.LPWSTR
LPCWSTR = wintypes.LPCWSTR
LPBYTE = wintypes.LPBYTE

_INVALID_INPUT = "WINDOWS_PROCESS_INVALID_INPUT"
_MAX_HANDLE = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100

HANDLE_FLAG_INHERIT = 0x00000001
ERROR_INSUFFICIENT_BUFFER = 122

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
INFINITE = 0xFFFFFFFF
_MAX_WAIT_SECONDS = 4294967.0
_CLOSE_WAIT_MILLISECONDS = 5000


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", LPVOID),
        ("bInheritHandle", BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", LPWSTR),
        ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", LPBYTE),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", LPVOID),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


def _native_error(tag, operation, code, detail=None):
    """Build a prefixed OSError while retaining the native error code."""
    message = f"WINDOWS_PROCESS_{tag}: {operation} failed"
    if detail:
        message = f"{message}: {detail}"
    if code:
        message = f"{message} (Windows error {code})"
        return OSError(code, message, None, code)
    return OSError(message)


def _operation_error(tag, detail):
    return OSError(f"WINDOWS_PROCESS_{tag}: {detail}")


def _wrapped_error(tag, operation, exc):
    """Convert a conversion/CRT failure into a prefixed OSError."""
    code = getattr(exc, "winerror", None)
    if isinstance(code, int) and code:
        return _native_error(tag, operation, code, str(exc))
    errno = getattr(exc, "errno", None)
    message = f"WINDOWS_PROCESS_{tag}: {operation} failed: {exc}"
    if isinstance(errno, int) and errno:
        return OSError(errno, message, None)
    return OSError(message)


def _handle_value(value):
    """Return an unsigned native handle value, or None for a non-handle."""
    if isinstance(value, ctypes.c_void_p):
        value = value.value
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _timeout_milliseconds(timeout):
    if timeout is None:
        return INFINITE
    if isinstance(timeout, bool) or not isinstance(timeout, numbers.Real):
        raise ValueError(
            "WINDOWS_PROCESS_INVALID_TIMEOUT: timeout must be a finite number")
    try:
        seconds = float(timeout)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "WINDOWS_PROCESS_INVALID_TIMEOUT: timeout must be a finite number"
        ) from exc
    if (
        not math.isfinite(seconds)
        or seconds < 0
        or seconds > _MAX_WAIT_SECONDS
    ):
        raise ValueError(
            "WINDOWS_PROCESS_INVALID_TIMEOUT: timeout must be between 0 and "
            "4294967 seconds")
    if seconds == 0:
        return 0
    milliseconds = int(math.ceil(seconds * 1000.0))
    if milliseconds < 1:
        milliseconds = 1
    if milliseconds > 0xFFFFFFFF:
        milliseconds = 0xFFFFFFFF
    return milliseconds


def _is_job_closed_error(exc):
    return isinstance(exc, RuntimeError) and str(exc) == "WINDOWS_JOB_CLOSED"


def _invalid(detail):
    return ValueError(f"{_INVALID_INPUT}: {detail}")


def _validate_argv(argv):
    if not isinstance(argv, (list, tuple)) or not argv:
        raise _invalid("argv must be a non-empty list or tuple")
    copied = []
    for item in argv:
        if not isinstance(item, str):
            raise _invalid("argv items must be strings")
        if "\x00" in item:
            raise _invalid("argv items must not contain NUL")
        copied.append(item)
    application = copied[0]
    if not application:
        raise _invalid("argv[0] must be nonempty")
    try:
        if not os.path.isabs(application) or not os.path.isfile(application):
            raise _invalid("argv[0] must be an absolute existing file")
    except (OSError, ValueError) as exc:
        raise _invalid("argv[0] must be an absolute existing file") from exc
    return tuple(copied)


def _validate_cwd(cwd):
    try:
        directory = os.fspath(cwd)
    except (TypeError, ValueError, OSError) as exc:
        raise _invalid("cwd must be an absolute existing directory") from exc
    if not isinstance(directory, str) or not directory:
        raise _invalid("cwd must be an absolute existing directory")
    if "\x00" in directory:
        raise _invalid("cwd must not contain NUL")
    try:
        if not os.path.isabs(directory) or not os.path.isdir(directory):
            raise _invalid("cwd must be an absolute existing directory")
    except (OSError, ValueError) as exc:
        raise _invalid("cwd must be an absolute existing directory") from exc
    return directory


def _validate_env(env):
    if not isinstance(env, dict):
        raise _invalid("env must be an explicit dict of str to str")
    entries = []
    seen = set()
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise _invalid("env keys and values must be strings")
        if not key or "=" in key or "\x00" in key:
            raise _invalid("env keys must be nonempty and contain no '=' or NUL")
        if "\x00" in value:
            raise _invalid("env values must not contain NUL")
        folded = key.upper()
        if folded in seen:
            raise _invalid("env contains case-insensitive duplicate keys")
        seen.add(folded)
        entries.append((key, value))
    entries.sort(key=lambda item: item[0].upper())
    # create_unicode_buffer adds the final NUL, making this double-NUL
    # terminated, including for an empty environment.
    return "\x00".join(f"{key}={value}" for key, value in entries) + "\x00"


class WindowsProcess:
    """One suspended native process owned by a caller-provided Windows job."""

    def __init__(self, argv, *, cwd, env, job, on_suspended=None):
        if os.name != "nt":
            raise OSError("WINDOWS_PROCESS_UNAVAILABLE")

        args = _validate_argv(argv)
        directory = _validate_cwd(cwd)
        environment = _validate_env(env)
        if on_suspended is not None and not callable(on_suspended):
            raise _invalid("on_suspended must be None or callable")
        try:
            raw_job_handle = job.handle
        except Exception as exc:
            raise _invalid("job.handle must be an open native job handle") from exc
        job_handle = _handle_value(raw_job_handle)
        if job_handle is None or job_handle <= 0 or job_handle > _MAX_HANDLE:
            raise _invalid("job.handle must be an open native job handle")

        self.args = args
        self.pid = None
        self.returncode = None
        self.stdin = None
        self.stdout = None
        self.stderr = None

        self._closed = True
        self._job = job
        self._job_handle = job_handle
        self._process_handle = None
        self._thread_handle = None
        self._startup_handles = []
        self._startup_fds = []
        self._startup_streams = []
        self._open_osfhandle = None
        self._binary_flag = 0

        attribute_buffer = None
        attribute_pointer = None
        attribute_initialized = False
        attribute_arrays = None

        self._load_native()
        try:
            security_attributes = SECURITY_ATTRIBUTES(
                ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)

            stdin_read, stdin_write = self._create_pipe(security_attributes)
            stdout_read, stdout_write = self._create_pipe(security_attributes)
            stderr_read, stderr_write = self._create_pipe(security_attributes)

            child_handles = (stdin_read, stdout_write, stderr_write)
            parent_write = stdin_write
            parent_reads = (stdout_read, stderr_read)
            for handle in (parent_write, *parent_reads):
                if not self._set_handle_information(
                    handle, HANDLE_FLAG_INHERIT, 0
                ):
                    code = ctypes.get_last_error()
                    raise _native_error(
                        "PIPE_INHERIT", "SetHandleInformation", code)

            attribute_size = SIZE_T()
            if not self._initialize_attribute_list(
                None, 2, 0, ctypes.byref(attribute_size)
            ):
                code = ctypes.get_last_error()
                if code != ERROR_INSUFFICIENT_BUFFER:
                    raise _native_error(
                        "ATTRIBUTE_LIST_SIZE",
                        "InitializeProcThreadAttributeList", code)
                if attribute_size.value <= 0:
                    raise _operation_error(
                        "ATTRIBUTE_LIST_SIZE",
                        "InitializeProcThreadAttributeList returned no size")

            attribute_buffer = ctypes.create_string_buffer(
                int(attribute_size.value))
            attribute_pointer = ctypes.cast(attribute_buffer, LPVOID)
            if not self._initialize_attribute_list(
                attribute_pointer, 2, 0, ctypes.byref(attribute_size)
            ):
                code = ctypes.get_last_error()
                raise _native_error(
                    "ATTRIBUTE_LIST_INIT",
                    "InitializeProcThreadAttributeList", code)
            attribute_initialized = True

            handle_list = (HANDLE * 3)(
                HANDLE(stdin_read), HANDLE(stdout_write), HANDLE(stderr_write))
            job_list = (HANDLE * 1)(HANDLE(job_handle))
            attribute_arrays = (handle_list, job_list)

            if not self._update_attribute(
                attribute_pointer, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.cast(handle_list, LPVOID), ctypes.sizeof(handle_list),
                None, None
            ):
                code = ctypes.get_last_error()
                raise _native_error(
                    "ATTRIBUTE_HANDLE_LIST",
                    "UpdateProcThreadAttribute", code)
            if not self._update_attribute(
                attribute_pointer, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST,
                ctypes.cast(job_list, LPVOID), ctypes.sizeof(job_list),
                None, None
            ):
                code = ctypes.get_last_error()
                raise _native_error(
                    "ATTRIBUTE_JOB_LIST", "UpdateProcThreadAttribute", code)

            command_buffer = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(self.args))
            environment_buffer = ctypes.create_unicode_buffer(environment)

            startup_info = STARTUPINFOEXW()
            startup_info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            startup_info.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup_info.StartupInfo.hStdInput = stdin_read
            startup_info.StartupInfo.hStdOutput = stdout_write
            startup_info.StartupInfo.hStdError = stderr_write
            startup_info.lpAttributeList = attribute_pointer.value

            process_info = PROCESS_INFORMATION()
            creation_flags = (
                CREATE_SUSPENDED
                | CREATE_UNICODE_ENVIRONMENT
                | EXTENDED_STARTUPINFO_PRESENT
                | CREATE_NO_WINDOW
            )
            if not self._create_process(
                self.args[0],
                command_buffer,
                None,
                None,
                True,
                creation_flags,
                ctypes.cast(environment_buffer, LPVOID),
                directory,
                ctypes.byref(startup_info),
                ctypes.byref(process_info),
            ):
                code = ctypes.get_last_error()
                raise _native_error("CREATE", "CreateProcessW", code)

            self._process_handle = _handle_value(process_info.hProcess)
            self._thread_handle = _handle_value(process_info.hThread)
            self.pid = int(process_info.dwProcessId)
            if not self._process_handle or not self._thread_handle:
                raise _operation_error(
                    "CREATE", "CreateProcessW returned incomplete handles")

            in_job = BOOL()
            if not self._is_process_in_job(
                self._process_handle, job_handle, ctypes.byref(in_job)
            ):
                code = ctypes.get_last_error()
                raise _native_error(
                    "JOB_VERIFY", "IsProcessInJob", code)
            if not in_job.value:
                raise _operation_error(
                    "JOB_VERIFY", "the new process is not in the supplied job")

            self._close_startup_handles(child_handles, "CHILD_HANDLE_CLOSE")

            self.stdin = self._make_raw_stream(
                stdin_write, "wb", os.O_WRONLY | self._binary_flag)
            self.stdout = self._make_raw_stream(
                stdout_read, "rb", os.O_RDONLY | self._binary_flag)
            self.stderr = self._make_raw_stream(
                stderr_read, "rb", os.O_RDONLY | self._binary_flag)

            if on_suspended is not None:
                on_suspended(self)

            resumed = self._resume_thread(self._thread_handle)
            if resumed == 0xFFFFFFFF:
                code = ctypes.get_last_error()
                raise _native_error("RESUME", "ResumeThread", code)
            if resumed != 1:
                raise _operation_error(
                    "RESUME",
                    f"ResumeThread returned {resumed}; expected 1")

            if not self._close_handle(self._thread_handle):
                code = ctypes.get_last_error()
                raise _native_error(
                    "THREAD_CLOSE", "CloseHandle", code)
            self._thread_handle = None

            self._startup_streams.clear()
            self._closed = False
        except BaseException:
            self._cleanup_startup()
            raise
        finally:
            if attribute_initialized:
                try:
                    self._delete_attribute_list(attribute_pointer)
                except BaseException:
                    pass
            attribute_arrays = None
            attribute_buffer = None
            attribute_pointer = None

    def _load_native(self):
        import msvcrt

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError as exc:
            raise _wrapped_error(
                "KERNEL32", "ctypes.WinDLL('kernel32')", exc) from exc
        self._kernel32 = kernel32
        self._open_osfhandle = msvcrt.open_osfhandle
        self._binary_flag = getattr(os, "O_BINARY", 0)

        self._create_pipe_api = kernel32.CreatePipe
        self._create_pipe_api.argtypes = [
            ctypes.POINTER(HANDLE),
            ctypes.POINTER(HANDLE),
            ctypes.POINTER(SECURITY_ATTRIBUTES),
            DWORD,
        ]
        self._create_pipe_api.restype = BOOL

        self._set_handle_information = kernel32.SetHandleInformation
        self._set_handle_information.argtypes = [HANDLE, DWORD, DWORD]
        self._set_handle_information.restype = BOOL

        self._initialize_attribute_list = (
            kernel32.InitializeProcThreadAttributeList)
        self._initialize_attribute_list.argtypes = [
            LPVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)]
        self._initialize_attribute_list.restype = BOOL

        self._update_attribute = kernel32.UpdateProcThreadAttribute
        self._update_attribute.argtypes = [
            LPVOID,
            DWORD,
            DWORD_PTR,
            LPVOID,
            SIZE_T,
            LPVOID,
            ctypes.POINTER(SIZE_T),
        ]
        self._update_attribute.restype = BOOL

        self._delete_attribute_list = (
            kernel32.DeleteProcThreadAttributeList)
        self._delete_attribute_list.argtypes = [LPVOID]
        self._delete_attribute_list.restype = None

        self._create_process = kernel32.CreateProcessW
        self._create_process.argtypes = [
            LPCWSTR,
            LPWSTR,
            ctypes.POINTER(SECURITY_ATTRIBUTES),
            ctypes.POINTER(SECURITY_ATTRIBUTES),
            BOOL,
            DWORD,
            LPVOID,
            LPCWSTR,
            ctypes.POINTER(STARTUPINFOEXW),
            ctypes.POINTER(PROCESS_INFORMATION),
        ]
        self._create_process.restype = BOOL

        self._is_process_in_job = kernel32.IsProcessInJob
        self._is_process_in_job.argtypes = [
            HANDLE, HANDLE, ctypes.POINTER(BOOL)]
        self._is_process_in_job.restype = BOOL

        self._resume_thread = kernel32.ResumeThread
        self._resume_thread.argtypes = [HANDLE]
        self._resume_thread.restype = DWORD

        self._terminate_process = kernel32.TerminateProcess
        self._terminate_process.argtypes = [HANDLE, DWORD]
        self._terminate_process.restype = BOOL

        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [HANDLE]
        self._close_handle.restype = BOOL

        self._wait_for_single_object = kernel32.WaitForSingleObject
        self._wait_for_single_object.argtypes = [HANDLE, DWORD]
        self._wait_for_single_object.restype = DWORD

        self._get_exit_code_process = kernel32.GetExitCodeProcess
        self._get_exit_code_process.argtypes = [
            HANDLE, ctypes.POINTER(DWORD)]
        self._get_exit_code_process.restype = BOOL

    def _create_pipe(self, security_attributes):
        read_handle = HANDLE()
        write_handle = HANDLE()
        if not self._create_pipe_api(
            ctypes.byref(read_handle),
            ctypes.byref(write_handle),
            ctypes.byref(security_attributes),
            0,
        ):
            code = ctypes.get_last_error()
            raise _native_error("PIPE_CREATE", "CreatePipe", code)

        read_value = _handle_value(read_handle)
        write_value = _handle_value(write_handle)
        if read_value:
            self._startup_handles.append(read_value)
        if write_value:
            self._startup_handles.append(write_value)
        if not read_value or not write_value:
            raise _operation_error(
                "PIPE_CREATE", "CreatePipe returned an invalid handle")
        return read_value, write_value

    def _close_startup_handles(self, handles, tag):
        first_error = None
        for handle in handles:
            if handle not in self._startup_handles:
                continue
            closed, error = self._try_close_native_handle(handle, tag)
            if closed:
                try:
                    self._startup_handles.remove(handle)
                except ValueError:
                    pass
            elif first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error

    def _make_raw_stream(self, handle, mode, flags):
        try:
            fd = self._open_osfhandle(int(handle), flags)
        except BaseException as exc:
            raise _wrapped_error(
                "PIPE_OPEN", "msvcrt.open_osfhandle", exc) from exc
        if fd < 0:
            raise _operation_error(
                "PIPE_OPEN", "msvcrt.open_osfhandle returned an invalid fd")

        # The CRT fd now owns the native pipe handle.
        try:
            self._startup_handles.remove(handle)
        except ValueError:
            pass
        self._startup_fds.append(fd)

        try:
            stream = os.fdopen(fd, mode, buffering=0)
        except BaseException as exc:
            try:
                self._startup_fds.remove(fd)
            except ValueError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            raise _wrapped_error("PIPE_STREAM", "os.fdopen", exc) from exc

        try:
            self._startup_fds.remove(fd)
        except ValueError:
            pass
        self._startup_streams.append(stream)
        return stream

    def _try_close_native_handle(self, handle, tag="HANDLE_CLOSE"):
        if handle is None:
            return True, None
        try:
            if self._close_handle(handle):
                return True, None
            code = ctypes.get_last_error()
            return False, _native_error(tag, "CloseHandle", code)
        except BaseException as exc:
            return False, _wrapped_error(tag, "CloseHandle", exc)

    def _cleanup_startup(self):
        """Best-effort startup rollback; never mask the active exception."""
        process_handle = self._process_handle
        if process_handle:
            try:
                self._job.terminate(1)
            except BaseException:
                pass
            try:
                self._terminate_process(process_handle, 1)
            except BaseException:
                pass
            try:
                self._wait_for_single_object(
                    process_handle, _CLOSE_WAIT_MILLISECONDS)
            except BaseException:
                pass

        if self._thread_handle:
            closed, _ = self._try_close_native_handle(
                self._thread_handle, "THREAD_CLOSE")
            if closed:
                self._thread_handle = None

        if process_handle:
            closed, _ = self._try_close_native_handle(
                process_handle, "PROCESS_CLOSE")
            if closed:
                self._process_handle = None

        for stream in list(self._startup_streams):
            try:
                stream.close()
            except BaseException:
                pass
            else:
                try:
                    self._startup_streams.remove(stream)
                except ValueError:
                    pass

        for fd in list(self._startup_fds):
            try:
                os.close(fd)
            except BaseException:
                pass
            else:
                try:
                    self._startup_fds.remove(fd)
                except ValueError:
                    pass

        for handle in list(self._startup_handles):
            closed, _ = self._try_close_native_handle(handle)
            if closed:
                try:
                    self._startup_handles.remove(handle)
                except ValueError:
                    pass

    def _read_exit_code(self):
        exit_code = DWORD()
        if not self._get_exit_code_process(
            self._process_handle, ctypes.byref(exit_code)
        ):
            code = ctypes.get_last_error()
            raise _native_error(
                "EXIT_CODE", "GetExitCodeProcess", code)
        return int(exit_code.value) & 0xFFFFFFFF

    def _wait_native(self, milliseconds):
        result = self._wait_for_single_object(
            self._process_handle, milliseconds)
        if result == WAIT_FAILED:
            code = ctypes.get_last_error()
            raise _native_error(
                "WAIT", "WaitForSingleObject", code)
        if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise _operation_error(
                "WAIT",
                f"WaitForSingleObject returned unexpected result {result}")
        return int(result)

    def _require_open(self):
        if self._closed:
            raise RuntimeError("WINDOWS_PROCESS_CLOSED")

    def poll(self):
        self._require_open()
        if self.returncode is not None:
            return self.returncode
        result = self._wait_native(0)
        if result == WAIT_TIMEOUT:
            return None
        self.returncode = self._read_exit_code()
        return self.returncode

    def wait(self, timeout=None):
        self._require_open()
        milliseconds = _timeout_milliseconds(timeout)
        if self.returncode is not None:
            return self.returncode
        result = self._wait_native(milliseconds)
        if result == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.returncode = self._read_exit_code()
        return self.returncode

    def kill(self):
        self._require_open()
        self._job.terminate(1)

    def _close_resources(self):
        errors = []

        try:
            self._job.terminate(1)
        except BaseException as exc:
            if not _is_job_closed_error(exc):
                errors.append(exc)

        if self._process_handle:
            try:
                if self._wait_native(_CLOSE_WAIT_MILLISECONDS)==WAIT_TIMEOUT:
                    errors.append(_operation_error('CLOSE_TIMEOUT','primary process did not exit'))
            except BaseException as exc:
                errors.append(exc)

        if self._thread_handle:
            closed, error = self._try_close_native_handle(
                self._thread_handle, "THREAD_CLOSE")
            if closed:
                self._thread_handle = None
            else:
                errors.append(error)

        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(self, name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except BaseException as exc:
                errors.append(_wrapped_error("STREAM_CLOSE", name, exc))

        if self._process_handle:
            closed, error = self._try_close_native_handle(
                self._process_handle, "PROCESS_CLOSE")
            if closed:
                self._process_handle = None
            else:
                errors.append(error)

        return errors

    def close(self):
        if self._closed:
            return
        self._closed = True
        errors = self._close_resources()
        if errors:
            raise errors[0]

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except BaseException:
                pass
        return False
