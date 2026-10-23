# Native worker process ownership, v1

Windows 10+ implementation module: `ModuleFolders/Infrastructure/Platform/WindowsProcess.py`.
Stdlib only. The caller creates one exclusive `WindowsJob` for this process tree.
This class manages native startup, pipes and process handles. It does not implement
adapter protocols, parse output, choose a command, scan processes, or read secrets.

## API

`WindowsProcess(argv, *, cwd, env, job, on_suspended=None)`:

- Windows only; other platforms raise `OSError('WINDOWS_PROCESS_UNAVAILABLE')`.
  Import must still work elsewhere; load kernel32/msvcrt lazily on construction.
- `argv` is a nonempty list/tuple of strings, NUL forbidden, argv[0] a nonempty
  absolute existing file. Preserve argument spelling and order, including empty
  strings and quotes. `cwd` is an absolute existing directory (str/PathLike).
- `env` is an explicit dict of str:str. Keys nonempty, no `=` or NUL, values no
  NUL. Reject case-insensitive duplicate keys. An empty dict is a double-NUL
  environment block, never ambient inheritance. Do not retain or log env values.
- Malformed values raise ValueError prefixed `WINDOWS_PROCESS_INVALID_INPUT`.
  Validate before allocating handles. No shell or file modification.
- `job.handle` must be an open native WindowsJob handle; caller owns job lifetime.
  `on_suspended` is None or callable; reject others before allocation.
- Expose `args` (copied tuple), `pid`, `returncode` (initially None), binary raw
  `stdin`, `stdout`, `stderr` streams. Constructor resumes the primary thread
  only after the ownership and pipe setup below succeeds.
- Optional `on_suspended(self)` runs once after membership verification and pipe
  setup, before ResumeThread. It supports startup observation/fault tests; a
  raised error aborts the child and cleans all startup resources.
- `poll()` returns None while running or cached unsigned DWORD exit code;
  `wait(timeout=None)` waits for completion, returns exit code, raises
  subprocess.TimeoutExpired(args, timeout) on finite timeout. Reject bool,
  negative, nonfinite, nonnumeric timeout or >4294967 seconds. Zero is allowed.
  Methods after close raise RuntimeError('WINDOWS_PROCESS_CLOSED').
- `kill()` invokes this exclusive job's terminate(1), preserving descendants.
  It never terminates a process by name/PID or touches another job.
- `close()` is idempotent: terminate all members of the exclusive job even if
  the primary process has already exited, wait up to 5 seconds for the primary,
  then close the three parent streams and the owned primary process handle.
  Do not close the caller's job handle. If the job has already been closed,
  ignore only WINDOWS_JOB_CLOSED; its kill-on-close contract already applies.
  __enter__ returns self when open, __exit__ closes, does not suppress exceptions.
  No destructor or background threads in this module.

## Startup and ownership (required, no downgrade)

Use ctypes.WinDLL('kernel32', use_last_error=True), correct argtypes/restype for
all APIs. Handles are pointer-width; DWORD/BOOL/WORD are Windows native widths.
Use ctypes.wintypes, c_size_t for SIZE_T and DWORD_PTR, c_void_p for attribute lists.

Create three anonymous pipes with SECURITY_ATTRIBUTES (DWORD nLength, LPVOID
lpSecurityDescriptor, BOOL bInheritHandle=True). Disable inheritance on the parent
write/read/read ends with SetHandleInformation(HANDLE_FLAG_INHERIT=1, mask=1,
flags=0). Only child read/write/write ends enter the inherited handle list.

STARTUPINFOW has documented fields: cb DWORD; lpReserved/lpDesktop/lpTitle LPWSTR;
dwX/dwY/dwXSize/dwYSize/dwXCountChars/dwYCountChars/dwFillAttribute/dwFlags DWORD;
wShowWindow/cbReserved2 WORD; lpReserved2 LPBYTE; hStdInput/hStdOutput/hStdError HANDLE.
STARTUPINFOEXW adds lpAttributeList LPVOID. PROCESS_INFORMATION has hProcess,
hThread HANDLE and dwProcessId,dwThreadId DWORD. SECURITY_ATTRIBUTES/STARTUPINFOEXW/
PROCESS_INFORMATION sizes on x64 should be 24/112/24.

InitializeProcThreadAttributeList for exactly 2 attributes (size query with NULL,
allocate buffer, initialize, delete once in finally). Attribute arrays must remain
alive until DeleteProcThreadAttributeList:

- PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002, array of three inheritable child
  pipe handles; bInheritHandles=True.
- PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D, array containing job.handle. This
  establishes membership at creation, covering parent death before later checks.

CreateProcessW with explicit absolute lpApplicationName and writable Unicode
command buffer from subprocess.list2cmdline(argv). Explicit sorted Unicode env
block; preserve original keys, sort case-insensitively, terminate double-NUL.
Flags: CREATE_SUSPENDED (4), CREATE_UNICODE_ENVIRONMENT (0x400),
EXTENDED_STARTUPINFO_PRESENT (0x80000), CREATE_NO_WINDOW (0x08000000).
StartupInfo.cb=sizeof(STARTUPINFOEXW), dwFlags=STARTF_USESTDHANDLES (0x100).
No breakaway, inherited job handle, alternate startup fallback or shell.

After CreateProcess succeeds: save only its returned process/thread handles and
PID, verify IsProcessInJob(hProcess,job.handle,&BOOL) is true, close child-side
pipe handles in parent, transfer parent ends using msvcrt.open_osfhandle and
os.fdopen(...,buffering=0). Then optional hook, ResumeThread (must return 1;
0xffffffff or other count is failure), close owned primary thread handle.

Native errors must be OSError with WINDOWS_PROCESS_<OPERATION> prefix and native
winerror preserved (capture error immediately). If startup fails at any point,
terminate the exclusive owned job as well as the returned process handle if it exists (a
failure after ResumeThread may already have created descendants), wait
boundedly, close thread/process and all owned pipe/fd/stream handles, destroy an
initialized attribute list once. Preserve the original error. Do not leak a
successfully transferred fd if os.fdopen fails. Do not close caller job handle.

poll/wait use WaitForSingleObject and GetExitCodeProcess. WAIT_TIMEOUT=258,
WAIT_OBJECT_0=0, WAIT_FAILED=0xffffffff. Keep primary process handle until close.
All cleanup branches must attempt every owned resource even if one cleanup call
fails. Under ordinary native failure surface cleanup error, while preserving an
already active body/startup exception rather than masking it.

## Authoritative API references

- [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
- [Extended attributes and JOB_LIST](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
- [Microsoft SDK header](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/processthreadsapi.h)

WindowsProcess is native plumbing only. Codex owns bounded I/O, cancellation,
adapter integration, native failure injection and final application acceptance.

## Python control input

One ProtocolInput reader owns stdin, first on the main thread for the request,
then on the controller thread for cancellation. It retains packed frame bytes.
On Windows it polls the anonymous pipe using PeekNamedPipe and reads only bytes
already available; a blocking CRT read on an idle pipe in another thread hangs
NumPy import in the tested Python runtime. Vendor stdin is replaced with an empty
StringIO, preventing concurrent reads of this synchronous pipe. This is a tested
workaround, not a claim about the precise NumPy internal cause. See the
[PeekNamedPipe API contract](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe),
including its caveat about concurrent I/O on synchronous handles.
