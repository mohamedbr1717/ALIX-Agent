import shutil
import tempfile
import unittest
from pathlib import Path

from core.sandbox import ProotSandbox, SandboxUnavailable


class TestProotSandboxAvailability(unittest.TestCase):
    """
    هذه الاختبارات تعمل بغض النظر عن توفر proot على الجهاز، وتتحقق
    تحديدًا من سلوك fail-closed: إن تعذّر ضمان عزل حقيقي، يجب أن يُرفض
    التنفيذ صراحة بدل التراجع الصامت لتشغيل غير معزول.
    """

    def test_unavailable_when_proot_missing(self):
        if shutil.which("proot") is not None:
            self.skipTest("proot مثبت على هذا الجهاز؛ هذا الاختبار يتحقق من حالة غيابه فقط.")

        with tempfile.TemporaryDirectory() as workspace:
            with self.assertRaises(SandboxUnavailable):
                ProotSandbox(workspace=Path(workspace))

    def test_unavailable_error_mentions_install_hint(self):
        if shutil.which("proot") is not None:
            self.skipTest("proot مثبت على هذا الجهاز.")

        with tempfile.TemporaryDirectory() as workspace:
            try:
                ProotSandbox(workspace=Path(workspace))
                self.fail("كان يجب رفع SandboxUnavailable")
            except SandboxUnavailable as exc:
                self.assertIn("pkg install proot", str(exc))


@unittest.skipUnless(
    shutil.which("proot") is not None,
    "يتطلب تثبيت proot لتشغيل اختبارات العزل الفعلي "
    "(pkg install proot على Termux، أو apt-get install proot على لينكس)",
)
class TestProotSandboxRealExecution(unittest.TestCase):
    """
    اختبارات تكاملية حقيقية -- تُشغَّل فقط عندما يكون proot متوفرًا
    فعليًا (على Termux، أو على CI بعد إضافة خطوة تثبيته). هذه هي
    الاختبارات التي تثبت أن العزل يعمل فعليًا، لا فقط أن الكود
    يُصرَّف بدون أخطاء.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.sandbox = ProotSandbox(workspace=self.workspace)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, code: str) -> Path:
        path = self.workspace / name
        path.write_text(code, encoding="utf-8")
        return path

    def test_basic_execution_works(self):
        script = self._write("ok.py", "print('hello-from-jail')")
        result = self.sandbox.run(script_path=script, timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertIn("hello-from-jail", result["stdout"])

    def test_cannot_read_outside_workspace(self):
        # ملف خارج مجلد العمل تمامًا -- يجب ألا يكون مرئيًا داخل الـ jail.
        outside = Path(self.tmp.name).parent / "alix_sandbox_probe_secret.txt"
        outside.write_text("SECRET-OUTSIDE-WORKSPACE", encoding="utf-8")

        try:
            script = self._write(
                "probe.py",
                f"open({str(outside)!r}).read()",
            )
            result = self.sandbox.run(script_path=script, timeout=10)
            self.assertFalse(result["ok"])

            # يجب أن يكون الفشل بسبب خطأ Python عادي عند فتح ملف غير
            # موجود (لأن proot يخفيه)، لا بسبب انهيار المفسّر نفسه
            # (SIGABRT/mmap OOM) الذي كان سيمرّر هذا الاختبار خطأً
            # لسبب غير متعلق بالعزل إطلاقًا.
            self.assertNotEqual(
                result.get("return_code"),
                -6,
                f"فشل السكربت بانهيار للذاكرة لا بمنع proot الفعلي: {result}",
            )
            self.assertNotIn(
                "mmap failed",
                result.get("stderr", ""),
            )
            self.assertIn(
                "Error",
                result.get("stderr", ""),
                f"كان متوقعًا خطأ Python واضح (مثل FileNotFoundError) في stderr: {result}",
            )
        finally:
            outside.unlink(missing_ok=True)

    def test_cpu_limit_kills_busy_loop(self):
        script = self._write(
            "busy.py",
            "x = 0\n"
            "while True:\n"
            "    x += 1\n",
        )
        sandbox = ProotSandbox(
            workspace=self.workspace,
            max_cpu_seconds=1,
        )
        result = sandbox.run(script_path=script, timeout=10)
        self.assertFalse(result["ok"])

    def test_fork_bomb_is_blocked_by_nproc_limit(self):
        script = self._write(
            "forkbomb.py",
            "import os\n"
            "while True:\n"
            "    os.fork()\n",
        )
        sandbox = ProotSandbox(
            workspace=self.workspace,
            max_processes=4,
        )
        result = sandbox.run(script_path=script, timeout=10)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
