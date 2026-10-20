#!/usr/bin/env python3
"""Sistem komut yürütücüsü ve yetki yönetimi."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from enum import Enum
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.process import (
    NATIVE_OPERATION_LOCK,
    critical_command,
    redact_text,
    stream_process,
    terminate_process,
)


class OperationState(str, Enum):
    """Bir komut veya işlemin yaşam döngüsü durumları."""
    RUNNING = "RUNNING"
    TIMEOUT_WARNING = "TIMEOUT_WARNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class OperationContext:
    """Tek bir komut veya alt sürecin iptal durumunu ve sahipliğini izole eden bağlam."""

    def __init__(
        self,
        op_id: str,
        command: list[str] | None = None,
        allow_cancel: bool = True,
        thread_id: int | None = None,
        parent_op_id: str | None = None,
        secrets: tuple[str, ...] = (),
    ):
        self.op_id = op_id
        self.command = command or []
        self.allow_cancel = allow_cancel
        self.thread_id = thread_id if thread_id is not None else threading.get_ident()
        self.parent_op_id = parent_op_id
        self.secrets = tuple(s for s in secrets if s)
        self.process: subprocess.Popen | None = None
        self.pid: int | None = None
        self.cancelled = False
        self.timed_out = False
        self.lingering = False
        self.state: OperationState = OperationState.RUNNING
        self.is_critical: bool = False
        self.returncode: int | None = None
        self.completed_event = threading.Event()


class CommandRunner:
    """Sistem komutlarını yürüten, yetkilendirme (sudo) ve akış (streaming) yöneten sınıf."""

    _class_lock = threading.RLock()
    _class_cond = threading.Condition(_class_lock)
    _active_critical_registry: dict[str, OperationContext] = {}

    def __init__(self):
        self.host_bridge_available = self._detect_host_bridge()
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self._thread_callbacks: dict[int, Callable[[str], None]] = {}
        self._op_callbacks: dict[str, Callable[[str], None]] = {}
        self._lingering_threads: dict[str, threading.Thread] = {}
        self._proc_lock = threading.RLock()
        self._proc_cond = threading.Condition(self._proc_lock)
        self._operations: dict[str, OperationContext] = {}
        self._thread_to_op: dict[int, str] = {}
        self._pid_to_op: dict[int, str] = {}
        self._thread_op_stack: dict[int, list[str]] = {}
        self._thread_bound_ops: dict[int, str] = {}
        self._op_counter: int = 0
        self._fallback_context: OperationContext | None = None

    def _ensure_state(self) -> None:
        if not hasattr(self, "_proc_lock"):
            self._proc_lock = threading.RLock()
        if not hasattr(self, "_operations"):
            self._operations = {}
        if not hasattr(self, "_thread_to_op"):
            self._thread_to_op = {}
        if not hasattr(self, "_pid_to_op"):
            self._pid_to_op = {}
        if not hasattr(self, "_thread_op_stack"):
            self._thread_op_stack = {}
        if not hasattr(self, "_thread_bound_ops"):
            self._thread_bound_ops = {}
        if not hasattr(self, "_thread_callbacks"):
            self._thread_callbacks = {}
        if not hasattr(self, "_op_callbacks"):
            self._op_callbacks = {}
        if not hasattr(self, "_lingering_threads"):
            self._lingering_threads = {}
        if not hasattr(self, "_proc_cond"):
            self._proc_cond = threading.Condition(self._proc_lock)
        if not hasattr(self, "_op_counter"):
            self._op_counter = 0
        if not hasattr(self, "_fallback_context"):
            self._fallback_context = None

    def bind_thread_op(self, op_id: str) -> None:
        """Mevcut thread'i belirli bir işlem kimliğiyle ilişkilendirir."""
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            self._thread_bound_ops[tid] = op_id
            self._thread_to_op[tid] = op_id
            stack = self._thread_op_stack.setdefault(tid, [])
            if op_id not in stack:
                stack.append(op_id)

    def unbind_thread_op(self, op_id: str | None = None) -> None:
        """Mevcut thread'in işlem kimliği ilişkisini ve izole callback kaydını güvenle temizler."""
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            target_op = op_id or self._thread_bound_ops.get(tid)
            if target_op:
                self._op_callbacks.pop(target_op, None)
            if tid in self._thread_bound_ops:
                if op_id is None or self._thread_bound_ops[tid] == op_id:
                    self._thread_bound_ops.pop(tid, None)
            stack = self._thread_op_stack.get(tid, [])
            if op_id and op_id in stack:
                stack.remove(op_id)
            elif stack:
                stack.pop()
            if stack:
                self._thread_to_op[tid] = stack[-1]
            elif tid in self._thread_bound_ops:
                worker_op = self._thread_bound_ops[tid]
                self._thread_to_op[tid] = worker_op
                self._thread_op_stack[tid] = [worker_op]
            else:
                self._thread_to_op.pop(tid, None)
                self._thread_op_stack.pop(tid, None)

    def _preserve_lingering_operation(self, context: OperationContext) -> None:
        """Kritik bir işlem timeout olduğunda ancak alt süreç hâlâ yaşıyorken takipten düşmesini engeller."""
        self._ensure_state()
        with self._proc_lock:
            context.timed_out = True
            context.lingering = True
            context.state = OperationState.TIMEOUT_WARNING
            self._operations[context.op_id] = context
            if context.is_critical:
                with CommandRunner._class_lock:
                    CommandRunner._active_critical_registry[context.op_id] = context
                    CommandRunner._class_cond.notify_all()
            if context.process is not None and getattr(context.process, "pid", None) is not None:
                context.pid = context.process.pid
                self._pid_to_op[context.pid] = context.op_id
            tid = context.thread_id
            stack = self._thread_op_stack.get(tid, [])
            if context.op_id in stack:
                stack.remove(context.op_id)
            if stack:
                self._thread_to_op[tid] = stack[-1]
            elif tid in self._thread_bound_ops:
                worker_op = self._thread_bound_ops[tid]
                self._thread_to_op[tid] = worker_op
                self._thread_op_stack[tid] = [worker_op]
            else:
                self._thread_to_op.pop(tid, None)
                self._thread_op_stack.pop(tid, None)

            # Çıktı tamponunun dolup sürecin kilitlenmesini önleyen ve tamamlanmayı izleyen drainer'ı başlat
            self._start_lingering_drainer(context)

    def _start_lingering_drainer(self, context: OperationContext) -> None:
        """Kritik lingering sürecin stdout ve stderr borularını eşzamanlı tüketir, pipe kilitlenmesini önler ve bitişini izler."""
        if context.op_id in self._lingering_threads:
            return

        def _drain_and_reap():
            proc = context.process
            if proc is None:
                return

            max_log_lines = 1000
            drain_lock = threading.Lock()
            collected_lines: list[str] = []

            # 1. Çıktı kanallarını (stdout ve stderr) eşzamanlı ayrı thread'lerde sürekli tüketerek
            # child process'in pipe buffer dolmasıyla takılmasını/kilitlenmesini (P0-01) engelle
            reap_lock = threading.Lock()
            reaped = False

            def _drain_stream(stream):
                if not stream:
                    return
                try:
                    while True:
                        # Satırsız uzun çıktı ve bellek sınırlandırması için en fazla 8192 byte/karakter oku (P0-01)
                        if hasattr(stream, "readline"):
                            line = stream.readline(8192)
                        elif hasattr(stream, "read"):
                            line = stream.read(8192)
                        else:
                            break
                        if not line:
                            break
                        line_str = (
                            line.strip()
                            if isinstance(line, str)
                            else line.decode("utf-8", errors="replace").strip()
                        )
                        if line_str:
                            combined_secrets = tuple(
                                set(filter(None, (self._sudo_password, *getattr(context, "secrets", ()))))
                            )
                            clean_line = redact_text(line_str, combined_secrets)
                            with drain_lock:
                                collected_lines.append(clean_line)
                                if len(collected_lines) > max_log_lines:
                                    collected_lines.pop(0)
                            cb = self._resolve_output_callback(op_id=context.op_id)
                            if cb:
                                try:
                                    cb(clean_line)
                                except Exception:
                                    pass
                except Exception:
                    pass

            stream_threads = []
            if proc.stdout and not proc.stdout.closed:
                t_out = threading.Thread(
                    target=_drain_stream,
                    args=(proc.stdout,),
                    daemon=True,
                    name=f"drain-out-{context.op_id}",
                )
                stream_threads.append(t_out)
                t_out.start()

            if proc.stderr and not proc.stderr.closed:
                t_err = threading.Thread(
                    target=_drain_stream,
                    args=(proc.stderr,),
                    daemon=True,
                    name=f"drain-err-{context.op_id}",
                )
                stream_threads.append(t_err)
                t_err.start()

            for st in stream_threads:
                st.join()

            # 2. Sürecin sonlanmasını bekle, gerçek exit code'u al ve zombi oluşumunu engelle
            try:
                proc.wait()
                context.returncode = proc.returncode
            except Exception:
                pass
            finally:
                if proc.stdout and not proc.stdout.closed:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                if proc.stderr and not proc.stderr.closed:
                    try:
                        proc.stderr.close()
                    except Exception:
                        pass

            # 3. Kilit ve durum yönetimini tam olarak tek bir kez icra et (P0-01)
            with reap_lock:
                if reaped:
                    return
                reaped = True

            with self._proc_lock:
                if context.returncode == 0:
                    context.state = OperationState.COMPLETED
                else:
                    context.state = OperationState.FAILED
                context.completed_event.set()
                self._lingering_threads.pop(context.op_id, None)
                self._finish_operation(context)
                self._proc_cond.notify_all()
            with CommandRunner._class_lock:
                CommandRunner._active_critical_registry.pop(context.op_id, None)
                CommandRunner._class_cond.notify_all()

        t = threading.Thread(
            target=_drain_and_reap,
            daemon=True,
            name=f"drainer-{context.op_id}",
        )
        self._lingering_threads[context.op_id] = t
        t.start()

    @classmethod
    def has_global_active_critical_operation(cls, exclude_op_id: str | None = None) -> bool:
        """Tüm CommandRunner örnekleri genelinde aktif/lingering kritik işlem olup olmadığını denetler (P0-03)."""
        with cls._class_lock:
            for op_id, ctx in list(cls._active_critical_registry.items()):
                if op_id == exclude_op_id:
                    continue
                if ctx.completed_event.is_set() or ctx.state in (OperationState.COMPLETED, OperationState.FAILED):
                    cls._active_critical_registry.pop(op_id, None)
                    continue
                if not ctx.is_critical:
                    cls._active_critical_registry.pop(op_id, None)
                    continue
                proc = ctx.process
                if proc is not None:
                    # Mock veya sahte nesneleri kontrol et: gerçek integer PID yoksa ve lingering değilse bloklama
                    pid = getattr(proc, "pid", None)
                    if pid is None or not isinstance(pid, int):
                        if not ctx.lingering:
                            cls._active_critical_registry.pop(op_id, None)
                            continue
                    poll_fn = getattr(proc, "poll", None)
                    if callable(poll_fn):
                        poll_val = poll_fn()
                        if poll_val is not None:
                            cls._active_critical_registry.pop(op_id, None)
                            continue
                        if isinstance(pid, int):
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                cls._active_critical_registry.pop(op_id, None)
                                continue
                            except PermissionError:
                                pass
                            except OSError:
                                cls._active_critical_registry.pop(op_id, None)
                                continue
                    return True
                elif ctx.lingering or ctx.state in (OperationState.RUNNING, OperationState.TIMEOUT_WARNING):
                    return True
            return False

    def _has_active_critical_operation(self, exclude_op_id: str | None = None) -> bool:
        """Aktif veya arka planda devam eden kritik bir transaction olup olmadığını denetler."""
        self._ensure_state()
        if CommandRunner.has_global_active_critical_operation(exclude_op_id=exclude_op_id):
            return True
        with self._proc_lock:
            for ctx in self._operations.values():
                if ctx.op_id == exclude_op_id:
                    continue
                if ctx.is_critical:
                    if ctx.process is not None:
                        if ctx.process.poll() is None:
                            return True
                    elif ctx.lingering or ctx.state in (OperationState.RUNNING, OperationState.TIMEOUT_WARNING):
                        return True
            return False

    def _wait_for_critical_transactions(
        self,
        exclude_op_id: str | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Devam eden kritik transaction'lar bitene kadar bekler (P0-03 - tüm CommandRunner nesneleri arasında koordinasyon)."""
        self._ensure_state()
        start = time.monotonic()
        while self._has_active_critical_operation(exclude_op_id=exclude_op_id):
            remaining = None
            if timeout is not None:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    return False
            wait_time = min(0.2, remaining) if remaining is not None else 0.2
            with CommandRunner._class_lock:
                if CommandRunner.has_global_active_critical_operation(exclude_op_id=exclude_op_id):
                    CommandRunner._class_cond.wait(timeout=wait_time)
            with self._proc_lock:
                if self._has_active_critical_operation(exclude_op_id=exclude_op_id):
                    self._proc_cond.wait(timeout=wait_time)
        return True

    def get_operation_context(self, op_id: str) -> OperationContext | None:
        """Belirtilen op_id veya parent_op_id ile ilişkili işlem bağlamını döner."""
        self._ensure_state()
        with self._proc_lock:
            ctx = self._operations.get(op_id)
            if ctx is not None:
                return ctx
            for c in self._operations.values():
                if c.parent_op_id == op_id:
                    return c
        with CommandRunner._class_lock:
            ctx = CommandRunner._active_critical_registry.get(op_id)
            if ctx is not None:
                return ctx
            for c in CommandRunner._active_critical_registry.values():
                if c.parent_op_id == op_id:
                    return c
        return None

    def is_operation_lingering(self, op_id: str) -> bool:
        """İşlemin arka planda çalışmaya devam edip etmediğini kontrol eder."""
        ctx = self.get_operation_context(op_id)
        return ctx is not None and ctx.lingering

    def poll_tracked_operations(self) -> None:
        """Hâlâ arka planda izlenen operasyonların durumunu kontrol eder ve bitenleri temizler."""
        self._ensure_state()
        with self._proc_lock:
            for op_id, ctx in list(self._operations.items()):
                if ctx.process is not None and ctx.process.poll() is not None:
                    self._finish_operation(ctx)
        with CommandRunner._class_lock:
            for op_id, ctx in list(CommandRunner._active_critical_registry.items()):
                if ctx.process is not None and ctx.process.poll() is not None:
                    CommandRunner._active_critical_registry.pop(op_id, None)
                    CommandRunner._class_cond.notify_all()

    def _create_operation(
        self,
        command: list[str] | None,
        allow_cancel: bool,
        op_id: str | None = None,
    ) -> OperationContext:
        self._ensure_state()
        with self._proc_lock:
            self.poll_tracked_operations()
            tid = threading.get_ident()
            bound_worker_op = self._thread_bound_ops.get(tid)
            current_thread_op = self._thread_to_op.get(tid)
            bound_op_id = bound_worker_op or current_thread_op

            if op_id is None:
                if bound_worker_op and bound_worker_op not in self._operations:
                    # UI tarafından bağlanan işlem kimliğini kullan (1. veya sonraki komut)
                    op_id = bound_worker_op
                elif bound_op_id and bound_op_id not in self._operations:
                    op_id = bound_op_id
                else:
                    self._op_counter += 1
                    op_id = f"op_{self._op_counter}_{tid}"

            context = OperationContext(
                op_id,
                command=command,
                allow_cancel=allow_cancel,
                thread_id=tid,
                parent_op_id=bound_worker_op,
                secrets=(self._sudo_password,) if self._sudo_password else (),
            )
            context.is_critical = not allow_cancel or critical_command(command or [])
            self._operations[op_id] = context
            if context.is_critical:
                with CommandRunner._class_lock:
                    CommandRunner._active_critical_registry[op_id] = context
                    CommandRunner._class_cond.notify_all()
            stack = self._thread_op_stack.setdefault(tid, [])
            if op_id not in stack:
                stack.append(op_id)
            self._thread_to_op[tid] = op_id
            self._fallback_context = context
            return context

    def _attach_process(self, context: OperationContext, process: subprocess.Popen | None) -> None:
        self._ensure_state()
        with self._proc_lock:
            if process is not None:
                context.process = process
                pid = getattr(process, "pid", None)
                if pid:
                    context.pid = pid
                    self._pid_to_op[pid] = context.op_id
            else:
                # Teardown bildirimi (on_start(None)): Eski PID eşlemesini yalnızca süreç gerçekten bitmişse düşür
                if context.process is None or context.process.poll() is not None:
                    if context.pid and context.pid in self._pid_to_op:
                        self._pid_to_op.pop(context.pid, None)
                    context.process = None

    def _finish_operation(self, context: OperationContext) -> None:
        self._ensure_state()
        with self._proc_lock:
            if context.returncode is None and context.process is not None:
                context.returncode = context.process.poll()
            if context.state in (OperationState.RUNNING, OperationState.TIMEOUT_WARNING):
                context.state = (
                    OperationState.COMPLETED
                    if context.returncode == 0
                    else OperationState.FAILED
                )
            context.completed_event.set()

            # 1. PID eşlemesini idempotent temizle
            if context.pid:
                self._pid_to_op.pop(context.pid, None)
            if context.process is not None:
                pid = getattr(context.process, "pid", None)
                if pid:
                    self._pid_to_op.pop(pid, None)
            for p, oid in list(self._pid_to_op.items()):
                if oid == context.op_id:
                    self._pid_to_op.pop(p, None)

            # 2. Thread stack'inden çıkar ve iç operasyon bittiğinde dış operasyonu geri yükle (P1-01)
            tid = context.thread_id
            stack = self._thread_op_stack.get(tid, [])
            if context.op_id in stack:
                stack.remove(context.op_id)
            if stack:
                self._thread_to_op[tid] = stack[-1]
            elif tid in self._thread_bound_ops:
                # Worker thread hâlâ aktif! İkinci ve sonraki komutlar için worker op_id'sini koru
                worker_op = self._thread_bound_ops[tid]
                self._thread_to_op[tid] = worker_op
                self._thread_op_stack[tid] = [worker_op]
            else:
                self._thread_to_op.pop(tid, None)
                self._thread_op_stack.pop(tid, None)

            # 3. Operations tablosundan ve callback kayıtlarından kaldır
            self._operations.pop(context.op_id, None)
            if context.is_critical:
                with CommandRunner._class_lock:
                    CommandRunner._active_critical_registry.pop(context.op_id, None)
                    CommandRunner._class_cond.notify_all()
            # Worker thread'e bağlı kalıcı op_id'yi veya UI callback'ini erken silme (P1-01)
            # UI seviyesi op callback'leri worker bittiğinde unbind_thread_op veya set_output_callback(None, op_id=...) ile temizlenir.

            # 4. Fallback bağlamını güncelle
            if self._fallback_context is context:
                self._fallback_context = next(reversed(list(self._operations.values())), None)

            # 5. Bekleyen transaction'ları uyandır
            self._proc_cond.notify_all()

    @property
    def _current_process(self) -> subprocess.Popen | None:
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                return self._operations[op_id].process
            if self._fallback_context is not None:
                return self._fallback_context.process
            return None

    @_current_process.setter
    def _current_process(self, proc: subprocess.Popen | None) -> None:
        if proc is not None:
            self._register_process(proc, allow_cancel=getattr(self, "_cancel_allowed", False))
        else:
            self._unregister_process()

    @property
    def _cancel_allowed(self) -> bool:
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                return self._operations[op_id].allow_cancel
            if self._fallback_context is not None:
                return self._fallback_context.allow_cancel
            return False

    @_cancel_allowed.setter
    def _cancel_allowed(self, val: bool) -> None:
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                self._operations[op_id].allow_cancel = val
            elif self._fallback_context is not None:
                self._fallback_context.allow_cancel = val

    @property
    def _cancelled(self) -> bool:
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                return self._operations[op_id].cancelled
            if self._fallback_context is not None:
                return self._fallback_context.cancelled
            return False

    @_cancelled.setter
    def _cancelled(self, val: bool) -> None:
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                self._operations[op_id].cancelled = val
            elif self._fallback_context is not None:
                self._fallback_context.cancelled = val

    def _register_process(self, proc: subprocess.Popen | None, allow_cancel: bool) -> None:
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                ctx = self._operations[op_id]
                ctx.allow_cancel = allow_cancel
                self._attach_process(ctx, proc)
            else:
                ctx = self._create_operation(None, allow_cancel=allow_cancel)
                self._attach_process(ctx, proc)

    def _unregister_process(self, proc: subprocess.Popen | None = None) -> None:
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            op_id = self._thread_to_op.get(tid)
            if op_id and op_id in self._operations:
                ctx = self._operations[op_id]
                self._finish_operation(ctx)
            elif self._fallback_context is not None:
                self._finish_operation(self._fallback_context)

    def cancel_current(self, target: str | int | subprocess.Popen | None = None) -> bool:
        """Çalışmakta olan aktif alt süreci veya belirtilen işlemi güvenli biçimde sonlandırır.

        Args:
            target: İptal edilecek işlemin op_id (str), PID veya thread_id (int),
                    ya da subprocess.Popen nesnesi. None ise çağıran thread'in işlemi
                    veya güvenli biçimde belirlenen tek aktif işlem hedeflenir.

        Returns:
            bool: İptal başarılıysa True; kritik/engellenmişse veya bulunamadıysa False.
        """
        self._ensure_state()
        with self._proc_lock:
            target_ctx: OperationContext | None = None

            self.poll_tracked_operations()
            # 1. Hedef açıkça belirtilmişse (PID, thread_id, op_id veya Popen)
            if target is not None:
                if isinstance(target, str):
                    target_ctx = self._operations.get(target)
                    if target_ctx is None:
                        for ctx in self._operations.values():
                            if (
                                ctx.parent_op_id == target
                                or self._thread_bound_ops.get(ctx.thread_id) == target
                            ):
                                target_ctx = ctx
                                break
                elif isinstance(target, int):
                    if target in self._pid_to_op:
                        target_ctx = self._operations.get(self._pid_to_op[target])
                    elif target in self._thread_to_op:
                        target_ctx = self._operations.get(self._thread_to_op[target])
                    if target_ctx is None:
                        for ctx in self._operations.values():
                            if getattr(ctx.process, "pid", None) == target or ctx.thread_id == target:
                                target_ctx = ctx
                                break
                else:
                    for ctx in self._operations.values():
                        if ctx.process is target or getattr(ctx.process, "pid", None) == getattr(target, "pid", None):
                            target_ctx = ctx
                            break
                # Belirtilen hedef işlem bulunamadıysa (veya zaten bitmişse) reddet
                if target_ctx is None:
                    return False

            # 2. Hedef None ise çağıran thread'in bağlamını kontrol et
            if target_ctx is None:
                tid = threading.get_ident()
                if tid in self._thread_to_op:
                    target_ctx = self._operations.get(self._thread_to_op[tid])
                elif tid in self._thread_bound_ops:
                    target_ctx = self._operations.get(self._thread_bound_ops[tid])

            # 3. Çağıran thread'e ait işlem yoksa (örn. UI main thread), aktif işlemleri incele
            if target_ctx is None:
                running_contexts = [
                    ctx for ctx in self._operations.values()
                    if ctx.process is None or getattr(ctx.process, "poll", lambda: None)() is None
                ]
                # P0-01: Birden fazla işlem varken hedef verilmemişse ASLA başka bir işlemi otomatik seçme!
                if len(running_contexts) > 1:
                    return False
                elif len(running_contexts) == 1:
                    target_ctx = running_contexts[0]
                elif self._fallback_context is not None:
                    target_ctx = self._fallback_context
                else:
                    return False

            # Kritik işlem politikası (Fail-Closed): Hedefli iptalde de kritik koruma zorunlu
            if not target_ctx.allow_cancel:
                return False

            # İptal durumunu yalnızca bu bağlamda izole et
            target_ctx.cancelled = True
            proc = target_ctx.process
            if proc is not None:
                poll_fn = getattr(proc, "poll", lambda: None)
                if poll_fn() is None:
                    terminate_process(proc)
                    try:
                        wait_fn = getattr(proc, "wait", None)
                        if wait_fn is not None:
                            wait_fn(timeout=0.8)
                    except (subprocess.TimeoutExpired, OSError):
                        terminate_process(proc, force=True)
            return True

    def set_sudo_password(self, password: str) -> None:
        """Yönetici parolasını ayarlar."""
        self._sudo_password = password

    def clear_sudo_password(self) -> None:
        """Hafızadaki yönetici parolasını temizler."""
        self._sudo_password = None

    def set_output_callback(
        self,
        callback: Callable[[str], None] | None,
        op_id: str | None = None,
    ) -> None:
        """Komut çıktısı satır bazlı akarken tetiklenecek izole geri çağırma işlevi (P1-01)."""
        self._ensure_state()
        with self._proc_lock:
            tid = threading.get_ident()
            if op_id is not None:
                # Açıkça op_id verildiğinde çağıran thread'i (örn. GTK main thread) kirletme! (P1-01)
                if callback is None:
                    self._op_callbacks.pop(op_id, None)
                else:
                    self._op_callbacks[op_id] = callback
                return

            effective_op_id = (
                self._thread_bound_ops.get(tid)
                or self._thread_to_op.get(tid)
            )

            if callback is None:
                if effective_op_id:
                    self._op_callbacks.pop(effective_op_id, None)
                self._thread_callbacks.pop(tid, None)
                if not self._op_callbacks and not self._thread_callbacks:
                    self._output_callback = None
            else:
                if effective_op_id:
                    self._op_callbacks[effective_op_id] = callback
                self._thread_callbacks[tid] = callback
                # Çapraz pencere sızıntısını önlemek için yalnızca başka op_callback yoksa fallback ata
                if not self._op_callbacks:
                    self._output_callback = callback

    def _resolve_output_callback(
        self,
        tid: int | None = None,
        op_id: str | None = None,
    ) -> Callable[[str], None] | None:
        """İlgili operasyon kimliği veya thread için izole edilmiş geri çağırma işlevini döner (P1-01)."""
        self._ensure_state()
        with self._proc_lock:
            if tid is None:
                tid = threading.get_ident()
            effective_op_id = (
                op_id
                or self._thread_to_op.get(tid)
                or self._thread_bound_ops.get(tid)
            )
            # 1. Öncelik: Doğrudan bu op_id için kaydedilmiş izole callback
            if effective_op_id and effective_op_id in self._op_callbacks:
                return self._op_callbacks[effective_op_id]
            # 2. Öncelik: Bu thread için kayıtlı callback
            if tid in self._thread_callbacks:
                return self._thread_callbacks[tid]
            # 3. Fallback: Başka aktif op_callback bulunmuyorsa genel callback
            if not self._op_callbacks:
                return self._output_callback
            return None

    def command_exists(self, command: str) -> bool:
        """Belirtilen komutun sistemde bulunup bulunmadığını kontrol eder."""
        if self.host_bridge_available:
            result = self.run(["sh", "-lc", f"command -v {shlex.quote(command)} >/dev/null 2>&1"], timeout=5)
            return result.returncode == 0
        return shutil.which(command) is not None

    def path_exists(self, path: str) -> bool:
        """Belirtilen dosya yolunun varlığını kontrol eder."""
        if self.host_bridge_available:
            result = self.run(["test", "-e", path], timeout=5)
            return result.returncode == 0
        return os.path.exists(path)

    def read_text(self, path: str) -> str:
        """Dosya içeriğini metin olarak okur."""
        if self.host_bridge_available and self.path_exists(path):
            result = self.run(["cat", path], timeout=10, check=True)
            return result.stdout

        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def list_desktop_files(self, directories: list[str]) -> list[str]:
        """Verilen dizinlerdeki .desktop dosyalarını listeler."""
        if self.host_bridge_available:
            script = (
                'for dir in "$@"; do [ -d "$dir" ] && find "$dir" -maxdepth 1 -type f -name "*.desktop"; done'
            )
            result = self.run(["sh", "-c", script, "desktop-scan", *directories], timeout=15)
            if result.returncode == 0:
                return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})

        paths: list[str] = []
        for directory in directories:
            root = Path(directory).expanduser()
            if not root.exists():
                continue
            paths.extend(str(item) for item in root.glob("*.desktop") if item.is_file())
        return sorted(set(paths))

    def run(
        self,
        command: list[str],
        timeout: int = 30,
        check: bool = False,
        input_text: str | None = None,
        allow_cancel: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Standart bir komut çalıştırır."""
        wrapped = self._wrap_host(command)
        if allow_cancel is None:
            allow_cancel = not critical_command(wrapped)
        is_critical = not allow_cancel or critical_command(wrapped)
        with NATIVE_OPERATION_LOCK if is_critical else nullcontext():
            if is_critical:
                self._wait_for_critical_transactions()
            if timeout >= 120 or self._resolve_output_callback() is not None:
                return self._run_streaming(wrapped, timeout, check, stdin_text=input_text, allow_cancel=allow_cancel)
            return self._run_subprocess(wrapped, command, timeout, check, input_text, allow_cancel=allow_cancel)

    def run_read_only(
        self,
        command: list[str],
        timeout: int = 30,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a read-only query that can be cancelled as a provider times out."""
        wrapped = self._wrap_host(command)
        return self._run_subprocess(wrapped, command, timeout, check, None, allow_cancel=True)

    def _run_subprocess(
        self,
        wrapped: list[str],
        display_command: list[str],
        timeout: int,
        check: bool,
        input_text: str | None,
        allow_cancel: bool,
    ) -> subprocess.CompletedProcess[str]:
        context = self._create_operation(wrapped, allow_cancel=allow_cancel)
        is_critical = not allow_cancel or critical_command(wrapped)
        process: subprocess.Popen[str] | None = None
        child_env = dict(os.environ)
        for name in (
            "GTK_PATH",
            "GTK3_MODULES",
            "GTK_EXE_PREFIX",
            "GTK_IM_MODULE_FILE",
            "GDK_PIXBUF_MODULEDIR",
            "GDK_PIXBUF_MODULE_FILE",
            "GIO_MODULE_DIR",
            "GSETTINGS_SCHEMA_DIR",
            "LOCPATH",
        ):
            child_env.pop(name, None)
        if "/snap/" in child_env.get("LD_LIBRARY_PATH", ""):
            child_env.pop("LD_LIBRARY_PATH", None)
        try:
            process = subprocess.Popen(
                wrapped,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
                env=child_env,
            )
            self._attach_process(context, process)
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            if context.cancelled:
                raise BackendError("Operation cancelled.")
            result = subprocess.CompletedProcess(wrapped, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as exc:
            if process is not None and not is_critical:
                terminate_process(process, force=True)
                process.communicate()
            msg = (
                f"Kritik paket işlemi zaman aşımına uğradı: {' '.join(display_command)}\n{exc}\n"
                "Paket veritabanının bütünlüğünü korumak için zorla sonlandırılmadı ve süreç arka planda devam ediyor."
                if is_critical
                else f"Komut calistirilamadi: {' '.join(display_command)}\n{exc}"
            )
            raise BackendError(redact_text(msg, (self._sudo_password,))) from exc
        except OSError as exc:
            raise BackendError(
                redact_text(f"Komut calistirilamadi: {' '.join(display_command)}\n{exc}", (self._sudo_password,))
            ) from exc
        finally:
            if is_critical and process is not None and process.poll() is None:
                self._preserve_lingering_operation(context)
            else:
                self._finish_operation(context)

        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(
                redact_text(f"Komut basarisiz oldu: {' '.join(display_command)}\n{stderr}", (self._sudo_password,))
            )
        return result

    def _run_streaming(
        self,
        wrapped_command: list[str],
        timeout: int,
        check: bool,
        stdin_text: str | None = None,
        allow_cancel: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Komut çıktısını gerçek zamanlı olarak okur ve callback'e iletir."""
        if allow_cancel is None:
            allow_cancel = not critical_command(wrapped_command)
        is_critical = not allow_cancel or critical_command(wrapped_command)
        with NATIVE_OPERATION_LOCK if is_critical else nullcontext():
            if is_critical:
                self._wait_for_critical_transactions()
            return self._run_streaming_locked(wrapped_command, timeout, check, stdin_text, allow_cancel=allow_cancel)

    def _run_streaming_locked(self, wrapped_command, timeout, check, stdin_text, allow_cancel=True):
        context = self._create_operation(wrapped_command, allow_cancel=allow_cancel)
        secrets = (self._sudo_password,)
        is_critical = not allow_cancel or critical_command(wrapped_command)
        try:
            def started(process):
                self._attach_process(context, process)

            result = stream_process(
                wrapped_command,
                timeout,
                self._resolve_output_callback(threading.get_ident()),
                stdin_text,
                started,
                secrets,
                lambda: context.cancelled,
                critical=is_critical,
            )
            if context.cancelled:
                raise BackendError("Operation cancelled.")
            if check and result.returncode != 0:
                tail = "\n".join(result.stdout.splitlines()[-3:])
                raise BackendError(redact_text(
                    f"Komut basarisiz oldu: {' '.join(wrapped_command)}\n{tail}", secrets,
                ))
            return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(redact_text(
                f"Komut calistirilamadi: {' '.join(wrapped_command)}\n{exc}", secrets,
            )) from None
        finally:
            if is_critical and context.process is not None and context.process.poll() is None:
                self._preserve_lingering_operation(context)
            else:
                self._finish_operation(context)

    def run_privileged(
        self,
        command: list[str],
        timeout: int = 900,
        input_text: str | None = None,
        allow_cancel: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Ayrıcalıklı (sudo) komut çalıştırır.

        Fail-closed güvenlik politikası: allow_cancel açıkça True verilmedikçe
        ayrıcalıklı işlemler varsayılan olarak iptal edilemez (allow_cancel=False).
        """
        if allow_cancel is None:
            allow_cancel = False
        with NATIVE_OPERATION_LOCK:
            self._wait_for_critical_transactions()
            try:
                return self._run_privileged_locked(command, timeout, input_text, allow_cancel=allow_cancel)
            finally:
                self.clear_sudo_password()

    def _run_privileged_locked(self, command, timeout, input_text, allow_cancel=False):
        if allow_cancel is None:
            allow_cancel = False
        self._wait_for_apt_locks(command)
        sudo_probe = self.run(["sudo", "-n", "true"], timeout=5, allow_cancel=False)
        if sudo_probe.returncode == 0:
            result = self.run(["sudo", "-n", *command], timeout=timeout, input_text=input_text, allow_cancel=allow_cancel)
            self._raise_for_privileged_result(result, command)
            return result

        if not self._sudo_password:
            raise AuthRequiredError(
                "Yonetici parolasi gerekiyor. Canli onizlemeyi uygulama icinden acmak icin parolayi gir.",
            )

        stdin_text = f"{self._sudo_password}\n"
        if input_text is not None:
            stdin_text += input_text

        result = self.run(["sudo", "-S", "-p", "", *command], timeout=timeout, input_text=stdin_text, allow_cancel=allow_cancel)
        self._raise_for_privileged_result(result, command)
        return result

    def _raise_for_privileged_result(
        self,
        result: subprocess.CompletedProcess[str],
        command: list[str],
    ) -> None:
        if result.returncode != 0:
            combined = ((result.stderr or "") + "\n" + (result.stdout or "")).strip().lower()
            if any(kw in combined for kw in ("password", "try again", "incorrect", "sorry")):
                self.clear_sudo_password()
                raise AuthRequiredError(
                    "Yonetici parolasi hatali. Lutfen tekrar dene.",
                    password_failed=True,
                )
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(
                redact_text(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}", (self._sudo_password,))
            )

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        context = self._create_operation(["apt-lock-wait", *command], allow_cancel=True)
        started = time.monotonic()
        last_message = ""
        try:
            while True:
                if context.cancelled:
                    raise BackendError("Operation cancelled.")
                holders = self._apt_lock_holders()
                if not holders:
                    if last_message and self._output_callback is not None:
                        self._output_callback("APT kilidi boşaldı. İşleme devam ediliyor...")
                    return
                summary = "; ".join(f"PID {pid}: {args}" for pid, args in holders[:3])
                if len(holders) > 3:
                    summary += f"; +{len(holders) - 3} işlem"
                message = f"APT meşgul: {summary}"
                if message != last_message and self._output_callback is not None:
                    self._output_callback(message)
                    self._output_callback("Diğer APT işlemi bitince otomatik devam edilecek...")
                    last_message = message
                if time.monotonic() - started >= max_wait:
                    raise BackendError(f"APT şu anda başka bir işlem tarafından kullanılıyor.\n{summary}")
                sleep_end = time.monotonic() + 1.5
                while time.monotonic() < sleep_end:
                    if context.cancelled:
                        raise BackendError("Operation cancelled.")
                    time.sleep(0.1)
        finally:
            self._finish_operation(context)

    def _apt_lock_holders(self) -> list[tuple[str, str]]:
        script = r"""
locks="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock"
pids=""
if command -v fuser >/dev/null 2>&1; then
  for lock in $locks; do
    [ -e "$lock" ] || continue
    found="$(fuser "$lock" 2>/dev/null || true)"
    pids="$pids $found"
  done
fi
pids="$(printf '%s\n' $pids | awk '!seen[$1]++')"
if [ -n "$pids" ]; then
  ps -p "$(printf '%s,' $pids | sed 's/,$//')" -o pid=,args= 2>/dev/null || true
else
  ps -eo pid=,args= | awk '/[a]pt |[a]pt-get |[d]pkg |[u]nattended-upgrade/ && !/wait-for-signal/ {print}'
fi
"""
        try:
            result = self.run(["sh", "-lc", script], timeout=5)
        except Exception:
            return []
        holders: list[tuple[str, str]] = []
        current_pid = str(os.getpid())
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid, args = parts
            if pid == current_pid:
                continue
            lowered = args.lower()
            if not any(token in lowered for token in ("apt", "apt-get", "dpkg", "unattended-upgrade")):
                continue
            if "wait-for-signal" in lowered:
                continue
            holders.append((pid, args[:140]))
        return holders

    def spawn(self, command: list[str]) -> None:
        """Yeni bir işlem başlatır (arka planda çalışması için)."""
        try:
            subprocess.Popen(
                self._wrap_host(command),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise BackendError(f"Komut calistirilamadi: {' '.join(command)}\n{exc}") from exc

    def _wrap_host(self, command: list[str]) -> list[str]:
        if self.host_bridge_available:
            return ["flatpak-spawn", "--host", *command]
        return command

    def _detect_host_bridge(self) -> bool:
        if not shutil.which("flatpak-spawn"):
            return False

        result = subprocess.run(
            ["flatpak-spawn", "--host", "true"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
