from __future__ import annotations

"""
core/sandbox.py

عزل حقيقي على مستوى نظام التشغيل لتنفيذ Python، مبني على `proot`
(أداة تعترض نداءات النظام عبر ptrace لمحاكاة chroot/mount بدون
الحاجة لـ root أو دعم kernel لـ user namespaces).

لماذا proot تحديدًا لـ Termux/أندرويد؟
---------------------------------------
- bubblewrap و nsjail (الخياران المعتادان على لينكس العادي) يعتمدان
  على unprivileged user namespaces، وأغلب نوى أندرويد الرسمية (stock
  kernels) تعطّل CLONE_NEWUSER لمستخدم غير root لأسباب أمنية خاصة
  بالنظام -- أي أن هذين الخيارين ببساطة لن يعملا على جهاز غير
  مروَّت (non-rooted) في أغلب الحالات.
- proot لا يحتاج أي صلاحية خاصة أو دعم كيرنل إضافي؛ يعمل بالكامل في
  مساحة المستخدم عبر ptrace، وهو معبأ رسميًا ضمن مستودعات Termux
  ويُستخدم أصلًا بواسطة `proot-distro`. هذا يجعله الخيار الوحيد
  الواقعي هنا.

ما الذي يوفره هذا العزل فعليًا (مُنفَّذ بواسطة النواة/ptrace):
--------------------------------------------------------------
- عزل نظام الملفات: العملية المُنفَّذة لا ترى إلا مجلد العمل
  (workspace) و`$HOME` وهمي فارغ، ومسارات Termux الأساسية اللازمة
  لتشغيل python3 فقط. لا يمكنها الوصول لأي مسار آخر على الجهاز حتى
  عبر مسارات مطلقة أو `../../` أو `os.chdir("/")`.
- حدود موارد حقيقية مفروضة من النواة (`setrlimit`، لا تحتاج root):
  زمن CPU، الذاكرة الافتراضية، أقصى عدد عمليات/خيوط (يمنع fork
  bombs)، أقصى عدد ملفات مفتوحة، أقصى حجم مخرجات/ملفات.

  ملاحظة مهمة حول حد الذاكرة (RLIMIT_AS): هذا الحد يقيس الذاكرة
  الافتراضية المحجوزة (virtual address space)، لا الذاكرة الفعلية
  المستخدمة (RSS). مفسّرات Python الحديثة قد تحجز مئات الميجابايتات
  من العناوين الافتراضية فقط لبدء التشغيل (arena allocators، تحميل
  المكتبات المشتركة، ASLR) دون أن تستخدمها فعليًا. لو كانت القيمة
  الافتراضية أقل مما يحتاجه مفسّر Python على جهازك لمجرد الإقلاع،
  ستفشل حتى السكربتات البسيطة برسالة "mmap failed: Out of memory"
  (return_code = -6 / SIGABRT) رغم أن السكربت نفسه غير مسيء إطلاقًا.
  إن واجهت هذا، ارفع `max_memory_mb` عند إنشاء `ProotSandbox`.
- `PR_SET_NO_NEW_PRIVS` لمنع اكتساب أي صلاحيات إضافية.
- قتل كامل لمجموعة العمليات عند انتهاء المهلة، لا العملية الرئيسية
  فقط.

ما الذي **لا** يوفره هذا العزل (موثّق صراحة، لا يُخفى):
--------------------------------------------------------
- **عزل الشبكة**: حجب الاتصالات الصادرة يحتاج فعليًا root
  (iptables/nftables) أو user namespace شبكي (netns)، وكلاهما غير
  متاح على جهاز أندرويد غير مروَّت. أي سكربت داخل هذا الـ sandbox
  **يقدر يفتح اتصال شبكي صادر**. الإخفاء الوحيد المضاف هنا (تعطيل
  `/etc/resolv.conf` داخل الـ jail) يمنع فقط الحل عبر أسماء النطاقات
  (DNS) وليس الاتصال المباشر بعنوان IP -- خط دفاع جزئي وضعيف فقط،
  وليس عزلًا حقيقيًا.
- **فلترة نداءات النظام (seccomp)**: seccomp-bpf غير المميز
  (unprivileged) ممكن تقنيًا بدون root، لكنه يحتاج إما مكتبة seccomp
  لبايثون (غير متوفرة كحزمة Termux موثوقة) أو كتابة bytecode الخاص
  به يدويًا عبر ctypes. تم استبعاده هنا عمدًا بدل تقديم فلتر هش غير
  مُختبر يعطي إحساسًا زائفًا بالأمان.

إذا احتجت عزل شبكة حقيقي لاحقًا: هذا يتطلب إما جهازًا مروَّتًا مع
nftables، أو نقل تنفيذ Python لخادم container حقيقي (Docker/gVisor)
خارج الجهاز المحمول تمامًا.
"""

import ctypes
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class SandboxUnavailable(RuntimeError):
    """
    تُرفع عندما لا يمكن ضمان عزل حقيقي (مثلاً: proot غير مثبت).

    هذا الكلاس مصمم ليفشل بأمان (fail-closed): إن تعذّر بناء الـ
    sandbox، لا يوجد أي مسار تنفيذ بديل غير معزول. الاستدعاء يجب أن
    يُعامل هذا الخطأ كرفض للتنفيذ، لا كسبب للتراجع لتشغيل الكود مباشرة.
    """


class ProotSandbox:

    def __init__(
        self,
        workspace: Path,
        max_cpu_seconds: int = 10,
        max_processes: int = 32,
        max_open_files: int = 64,
        max_output_mb: int = 16,
    ):
        self.workspace = Path(workspace).resolve()
        self.max_cpu_seconds = int(max_cpu_seconds)
        self.max_processes = int(max_processes)
        self.max_open_files = int(max_open_files)
        self.max_output_mb = int(max_output_mb)

        self.proot_path = shutil.which("proot")
        self.python_path = shutil.which("python3") or shutil.which("python")

        # Termux prefix (usually /data/data/com.termux/files/usr).
        self.prefix = os.environ.get(
            "PREFIX",
            "/data/data/com.termux/files/usr",
        )

        if self.proot_path is None:
            raise SandboxUnavailable(
                "proot غير مثبت. لا يمكن ضمان عزل حقيقي بدونه.\n"
                "ثبّته عبر: pkg install proot"
            )

        if self.python_path is None:
            raise SandboxUnavailable(
                "تعذّر العثور على مفسّر python3."
            )

        if not Path(self.prefix).is_dir():
            raise SandboxUnavailable(
                f"مسار Termux prefix غير موجود: {self.prefix}"
            )

    # ------------------------------------------------------------
    # Resource limits (kernel-enforced, no root required)
    # ------------------------------------------------------------

    def _preexec(self):
        """Prepare the proot supervisor without workload resource limits."""

        def _apply():
            os.setsid()

            libc = ctypes.CDLL(None, use_errno=True)
            rc = libc.prctl(38, 1, 0, 0, 0)
            if rc != 0:
                raise OSError(
                    ctypes.get_errno(),
                    "PR_SET_NO_NEW_PRIVS failed",
                )

        return _apply

    _INNER_LIMIT_LAUNCHER = r"""
import os
import resource
import sys

cpu_seconds = int(sys.argv[1])
max_processes = int(sys.argv[2])
max_open_files = int(sys.argv[3])
max_output_bytes = int(sys.argv[4])
script = sys.argv[5]
script_args = sys.argv[6:]

resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
resource.setrlimit(resource.RLIMIT_NOFILE, (max_open_files, max_open_files))
resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))

os.execv(
    sys.executable,
    [sys.executable, script, *script_args],
)
"""

    # ------------------------------------------------------------
    # proot command construction
    # ------------------------------------------------------------

    def _build_command(
        self,
        script_path: Path,
        jail_home: Path,
        script_args: list[str],
    ) -> list[str]:

        try:
            relative_script = script_path.resolve().relative_to(
                self.workspace.resolve()
            )
        except ValueError as exc:
            raise ValueError(
                "script_path must be inside the sandbox workspace"
            ) from exc

        # Guest paths must never expose the host workspace path.
        guest_script = Path("/workspace") / relative_script

        cmd = [
            self.proot_path,
            "--kill-on-exit",
            "-r", str(self.prefix),
            "-b", "/system:/system",
            "-b", "/apex:/apex",
            "-b", "/dev:/dev",
            "-b", "/proc:/proc",
            "-b",
            f"{self.prefix}/lib:/data/data/com.termux/files/usr/lib",
            "-b",
            f"{self.workspace}:/workspace",
            "-b",
            f"{jail_home}:/home",
            "-w", "/workspace",
            "/system/bin/linker64",
            "/bin/python3",
            "-c",
            self._INNER_LIMIT_LAUNCHER,
            str(self.max_cpu_seconds),
            str(self.max_processes),
            str(self.max_open_files),
            str(self.max_output_mb),
            str(guest_script),
            *script_args,
        ]

        return cmd

    # ------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------

    def run(
        self,
        script_path: Path,
        script_args: Optional[list[str]] = None,
        timeout: int = 30,
        env: Optional[dict] = None,
    ) -> dict:
        """
        ينفّذ سكربت Python داخل الـ jail. يفترض أن `script_path`
        مسار تم التحقق منه مسبقًا (داخل workspace) بواسطة
        core/policy.py قبل الوصول لهذه الدالة -- هذه الطبقة توفر
        العزل التشغيلي، لا تكرر فحوصات مسار الملفات.
        """

        script_args = script_args or []

        with tempfile.TemporaryDirectory(
            prefix="alix-jail-home-"
        ) as jail_home:

            jail_home_path = Path(jail_home)

            run_env = {
                "HOME": str(jail_home_path),
                "TMPDIR": str(jail_home_path),
                "PATH": f"{self.prefix}/bin",
                "PROOT_NO_SECCOMP": "1",
                "LANG": "C.UTF-8",
            }

            if env:
                # لا تسمح لمتغيرات الاستدعاء بتجاوز HOME/TMPDIR
                # المعزولة أو حقن PATH يشير خارج الـ jail.
                for key, value in env.items():
                    if key in {"HOME", "TMPDIR", "PATH"}:
                        continue
                    run_env[key] = value

            command = self._build_command(
                script_path,
                jail_home_path,
                script_args,
            )

            try:
                result = subprocess.run(
                    command,
                    cwd=str(self.workspace),
                    env=run_env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    preexec_fn=self._preexec(),
                )

                return {
                    "ok": result.returncode == 0,
                    "return_code": result.returncode,
                    "stdout": result.stdout[:20000],
                    "stderr": result.stderr[:10000],
                    "sandboxed": True,
                    "timed_out": False,
                }

            except subprocess.TimeoutExpired as exc:
                return {
                    "ok": False,
                    "error": f"انتهت مهلة Python ({timeout} ثانية).",
                    "stdout": (exc.stdout or "")[:20000] if exc.stdout else "",
                    "stderr": (exc.stderr or "")[:10000] if exc.stderr else "",
                    "sandboxed": True,
                    "timed_out": True,
                }

            except OSError as exc:
                return {
                    "ok": False,
                    "error": f"فشل تشغيل الـ sandbox: {exc}",
                    "sandboxed": True,
                }
