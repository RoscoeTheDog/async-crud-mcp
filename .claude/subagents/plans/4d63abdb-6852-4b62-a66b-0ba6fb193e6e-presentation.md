# Plan: Windows Service Error 1053 - Root Cause Analysis

## Context

**Problem**: The async-crud-mcp Windows daemon fails to start with error 1053 (service fails to respond to SCM within 30s). The service uses pywin32's `ServiceFramework` and `MultiUserDispatcher` to manage per-user MCP workers, similar to the working claude-jsonl-mcp implementation. Investigation reveals structural differences in module loading and DLL configuration.

**Solution**: The root cause is most likely that pythonservice.exe fails to load required DLLs before any Python code runs. Secondary issues include lazy module loading chains and potential registry mismatches. Fixes involve ensuring DLL availability, verifying registry configuration, and optionally flattening the Windows subpackage structure.

## Changes

### DLL Configuration and Registry Setup

#### File: `scripts/installer.py` (lines 195–259, 298–325)
- **Current**: Implements `configure_pywin32_dlls()` to copy `pywintypes*.dll`, `pythoncom*.dll`, `pythonservice.exe`, and Python runtime DLLs from site-packages to the venv root. Separately, `install_service()` delegates service registration to the daemon installer.
- **Verification needed**: Confirm that `configure_pywin32_dlls()` is actually executed during installation and that all required DLLs are successfully copied to `venv_dir/`. If this step fails silently or is skipped, pythonservice.exe cannot load at startup, producing error 1053 before any Python exception is logged.
- **Key detail**: Unlike claude-jsonl-mcp (which relies on pywin32 post-install script copying DLLs to System32), async-crud-mcp must handle venv-local DLL resolution itself.

### Module Import Structure (Lazy Loading)

#### File: `src/async_crud_mcp/daemon/windows/__init__.py` (lines 37–58)
- **Current**: Uses lazy `__getattr__` pattern that defers importing `DaemonService` and other symbols until they are accessed at runtime.
- **Issue**: When pythonservice.exe accesses `DaemonService` via the registry PythonClass value, it triggers an extra `importlib.import_module()` call within `__getattr__`. This adds latency to the load sequence and relies on `PyObject_GetAttr` working correctly during SCM startup.
- **Potential improvement**: Consider flattening to `daemon/windows_service.py` (matching claude-jsonl-mcp pattern) to eliminate the subpackage indirection.

#### File: `src/async_crud_mcp/daemon/__init__.py` (lines 57–96)
- **Current**: Uses lazy imports for Windows-specific modules. Contrast with claude-jsonl-mcp's eager conditional import: `if sys.platform == 'win32': try: from .windows_service import...`.
- **Note**: This is less critical than DLL resolution but contributes to overall load-time complexity.

### Service Class Registration

#### File: `src/async_crud_mcp/daemon/windows/windows_service.py` (lines 81–203, 210–380)
- **Current**: The `DaemonService` class implements `SvcDoRun()` correctly (line 159: calls `ReportServiceStatus(SERVICE_RUNNING)` as first action), eliminating in-SvcDoRun timing as cause of 1053.
- **Verification needed**: Confirm that the Windows registry entry `HKLM\SYSTEM\CurrentControlSet\Services\async-crud-mcp-daemon\PythonClass` contains exactly `async_crud_mcp.daemon.windows.windows_service.DaemonService`. Any mismatch will prevent pythonservice.exe from instantiating the service class.

## Files to Modify

| File | Change |
|------|--------|
| `scripts/installer.py` (L195–259) | Verify `configure_pywin32_dlls()` runs and logs success/failure; add explicit error handling if DLL copy fails. |
| `scripts/installer.py` (L298–325) | Ensure service registration includes correct PythonClass registry value. |
| `src/async_crud_mcp/daemon/windows/__init__.py` (L37–58) | (Optional) Replace lazy `__getattr__` with eager imports, or flatten module structure. |
| `src/async_crud_mcp/daemon/__init__.py` (L57–96) | (Optional) Consider eager Windows import pattern matching claude-jsonl-mcp. |

## Verification

1. **DLL Availability**: After installation, confirm these files exist in the venv:
   - `pythonservice.exe`
   - `pywintypes3XX.dll` (XX = Python version, e.g., 313)
   - `pythoncom3XX.dll`
   - `python3XX.dll`

2. **Registry Check**: Query the service registry entry:
   ```
   reg query "HKLM\SYSTEM\CurrentControlSet\Services\async-crud-mcp-daemon\PythonClass"
   ```
   Expected value: `async_crud_mcp.daemon.windows.windows_service.DaemonService`

3. **Windows Event Log**: Check `Application` log (source: `Service Control Manager` or `Python Service`) for 1053 errors immediately after failed start attempt. If DLL resolution fails, the error appears before any Python logging.

4. **Installation Logging**: Review installer output to confirm `configure_pywin32_dlls()` completed successfully and all DLLs were copied.

5. **Manual Service Start Test** (after fixes):
   ```
   net start async-crud-mcp-daemon
   ```
   Should complete within 30s or report specific error in Event Log.

## Key Design Decisions

- **DLL Local Copy vs. System32**: async-crud-mcp copies DLLs to venv (local isolation). claude-jsonl-mcp relies on System32 (pywin32 post-install). Local copy is more robust for CI/CD environments.
- **Lazy vs. Eager Windows Imports**: async-crud-mcp defers Windows module loading; claude-jsonl-mcp loads eagerly on Windows. Deferred loading reduces startup overhead but adds complexity in the critical SCM bootstrap path.
