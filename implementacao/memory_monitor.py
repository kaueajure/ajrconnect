"""Guest RAM telemetry through an opt-in RDP share; no hypervisor or RSS guesses."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile
import time

GIB = 1024 ** 3
START_COMMAND = r'\\tsclient\AJRMonitor\iniciar.cmd'
COLLECTOR = r'''# AJR Connect: read-only Windows physical RAM collector.
$ErrorActionPreference = 'Stop'
$root = '\\tsclient\AJRMonitor'
$session = '__SESSION__'
$mutex = [Threading.Mutex]::new($false, ('Local\AJRMonitor_' + $session))
if (-not $mutex.WaitOne(0)) { $mutex.Dispose(); exit }
$sequence = 0
try {
    $previous = Get-Content -LiteralPath "$root\memory.json" -Raw | ConvertFrom-Json
    if ($previous.session -eq $session) { $sequence = [long]$previous.sequence }
} catch { }
$missing = 0
try {
    while ($missing -lt 5) {
        try {
            $current = Get-Content -LiteralPath "$root\session.json" -Raw | ConvertFrom-Json
            if ($current.session -ne $session) { break }
            $os = Get-CimInstance -ClassName Win32_OperatingSystem
            $total = [long]$os.TotalVisibleMemorySize * 1024
            $used = $total - ([long]$os.FreePhysicalMemory * 1024)
            $sequence++
            $payload = @{ session = $session; sequence = $sequence; used_bytes = $used; total_bytes = $total }
            $json = $payload | ConvertTo-Json -Compress
            [IO.File]::WriteAllText("$root\memory.tmp", $json, [Text.UTF8Encoding]::new($false))
            Move-Item -LiteralPath "$root\memory.tmp" -Destination "$root\memory.json" -Force
            $missing = 0
        } catch { $missing++ }
        Start-Sleep -Seconds 3
    }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
'''


@dataclass(frozen=True)
class MemorySample:
    used_bytes: int
    total_bytes: int


class MemoryMonitor:
    """Session-scoped samples, freshness and one warning per threshold crossing."""
    def __init__(self, directory, session, limit_gib, *, clock=time.monotonic):
        self.directory = Path(directory)
        self.session = session
        self.limit_bytes = int(limit_gib * GIB)
        self.clock = clock
        self.sequence = -1
        self.updated = None
        self.sample = None
        self.acknowledged = False

    @classmethod
    def create(cls, root, limit_gib):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(prefix='ram-', dir=root))
        session = secrets.token_hex(16)
        try:
            for name, content in (
                ('session.json', json.dumps({'session': session})),
                ('monitor.ps1', COLLECTOR.replace('__SESSION__', session)),
                ('iniciar.cmd', '@echo off\r\nstart "" /min powershell.exe -NoProfile '
                 '-ExecutionPolicy Bypass -File "%~dp0monitor.ps1"\r\n')):
                path = directory / name
                path.write_text(content, encoding='utf-8')
                path.chmod(0o600)
            return cls(directory, session, limit_gib)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def read(self):
        try:
            descriptor = os.open(self.directory / 'memory.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                    raise ValueError('Invalid telemetry file')
                data = json.loads(os.read(descriptor, 4097))
            finally:
                os.close(descriptor)
            if not isinstance(data, dict) or data.get('session') != self.session:
                raise ValueError('Wrong telemetry session')
            sequence, used, total = (data.get(key) for key in ('sequence', 'used_bytes', 'total_bytes'))
            if not all(type(value) is int for value in (sequence, used, total)) or \
                    not 0 <= used <= total <= 2 ** 60 or total == 0 or sequence < 0:
                raise ValueError('Invalid telemetry counters')
            if sequence > self.sequence:
                self.sequence, self.updated = sequence, self.clock()
                self.sample = MemorySample(used, total)
        except (OSError, ValueError, UnicodeError):
            # Missing/partial/malformed samples are unavailable, never zero RAM.
            return None
        if self.updated is None or self.clock() - self.updated > 15:
            return None
        return self.sample

    def warning_needed(self, sample):
        if sample.used_bytes <= self.limit_bytes * .9:
            self.acknowledged = False
        return sample.used_bytes > self.limit_bytes and not self.acknowledged

    def acknowledge(self):
        self.acknowledged = True

    def close(self):
        shutil.rmtree(self.directory, ignore_errors=True)


def describe(sample):
    return f'{sample.used_bytes / GIB:.2f} GiB usados de {sample.total_bytes / GIB:.2f} GiB'
