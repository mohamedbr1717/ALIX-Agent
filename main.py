#!/usr/bin/env python3

from __future__ import annotations

import sys
import traceback

from core.agent import ALIXAgent


VERSION = "5.0"


def print_banner(agent: ALIXAgent) -> None:
    """عرض واجهة ALIX الرئيسية."""

    print(
        f"""
╔══════════════════════════════════════════════════════════╗
║                    ALIX AI AGENT V{VERSION}                 ║
║              HYBRID SECURE EXECUTION ENGINE              ║
╠══════════════════════════════════════════════════════════╣
║ • OpenRouter / Local LLM Hybrid Routing                  ║
║ • Policy-Based Workspace Isolation                       ║
║ • Safe Executor + Permission Control                     ║
║ • Tool Calling + Evidence Verification                   ║
║ • Persistent Atomic Memory                               ║
║ • Audit Logging                                          ║
╚══════════════════════════════════════════════════════════╝

🤖 ALIX جاهز.

الأوامر الخاصة:
  exit / quit / خروج     إغلاق ALIX
  status                 عرض حالة النظام
  memory                 إحصائيات الذاكرة
  clear-history          مسح سجل المحادثة
  help                   عرض المساعدة
"""
    )


def show_status(agent: ALIXAgent) -> None:
    """عرض حالة المكونات الرئيسية."""

    try:
        llm_status = agent.llm.status()
    except Exception as exc:
        llm_status = {
            "error": str(exc)
        }

    try:
        memory_status = agent.memory.stats()
    except Exception as exc:
        memory_status = {
            "error": str(exc)
        }

    print("\n━━━━━━━━━━ حالة ALIX ━━━━━━━━━━")

    print(
        "🌐 OpenRouter:",
        "مفعّل"
        if llm_status.get("remote_enabled")
        else "غير مفعّل"
    )

    print(
        "🔑 API Key:",
        "موجود"
        if llm_status.get("remote_configured")
        else "غير موجود"
    )

    print(
        "🧠 Remote Model:",
        llm_status.get(
            "remote_model",
            "غير معروف"
        )
    )

    print(
        "💻 Local Model:",
        llm_status.get(
            "local_model",
            "غير معروف"
        )
    )

    print(
        "🔒 Workspace:",
        str(agent.policy.workspace)
    )

    print(
        "📝 Audit Log:",
        str(agent.audit_log)
    )

    print(
        "💾 Memory Facts:",
        memory_status.get(
            "facts",
            0
        )
    )

    print(
        "⚙️ Preferences:",
        memory_status.get(
            "preferences",
            0
        )
    )

    print(
        "📚 History:",
        memory_status.get(
            "history",
            0
        )
    )

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def show_memory(agent: ALIXAgent) -> None:
    """عرض إحصائيات الذاكرة فقط."""

    try:

        stats = agent.memory.stats()

        print("\n━━━━━━━━━━ الذاكرة ━━━━━━━━━━")
        print(
            f"Facts        : {stats.get('facts', 0)}"
        )
        print(
            f"Preferences  : {stats.get('preferences', 0)}"
        )
        print(
            f"History      : {stats.get('history', 0)}"
        )
        print(
            f"Version      : {stats.get('version', 0)}"
        )
        print(
            f"Backup       : "
            f"{'موجود' if stats.get('backup_exists') else 'غير موجود'}"
        )
        print(
            f"Path         : {stats.get('path', '')}"
        )
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    except Exception as exc:

        print(
            f"❌ تعذر قراءة حالة الذاكرة: {exc}"
        )


def show_help() -> None:
    """عرض تعليمات الاستخدام."""

    print(
        """
━━━━━━━━━━ مساعدة ALIX ━━━━━━━━━━

اكتب طلبك باللغة العربية أو الإنجليزية.

أمثلة:
  حلل ملفات المشروع
  اعرض الملفات الموجودة
  ابحث عن كلمة معينة في الكود
  افحص حالة Git
  أنشئ ملف Python
  اقرأ ملفًا
  تحقق من هذا السكريبت

أوامر النظام:
  status
  memory
  clear-history
  help
  exit

⚠️ العمليات التي تغيّر الملفات أو تنفذ برامج
قد تطلب موافقة صريحة منك.
"""
    )


def clear_history(agent: ALIXAgent) -> None:
    """مسح تاريخ المحادثة من الذاكرة."""

    print(
        "\n⚠️ سيتم مسح سجل المحادثة المحفوظ."
    )

    answer = input(
        "هل أنت متأكد؟ [y/N]: "
    ).strip().lower()

    if answer not in {
        "y",
        "yes",
        "نعم"
    }:
        print("تم إلغاء العملية.")
        return

    try:

        if agent.memory.clear_history():

            # الاحتفاظ برسالة system فقط.
            agent.messages = [
                agent.messages[0]
            ]

            print(
                "✅ تم مسح سجل المحادثة."
            )

        else:

            print(
                "❌ تعذر مسح سجل المحادثة."
            )

    except Exception as exc:

        print(
            f"❌ خطأ أثناء المسح: {exc}"
        )


def handle_special_command(
    command: str,
    agent: ALIXAgent
) -> bool:
    """
    معالجة أوامر الواجهة.

    ترجع True إذا تمت معالجة الأمر.
    """

    normalized = command.strip().lower()

    if normalized in {
        "exit",
        "quit",
        "خروج"
    }:

        return True

    if normalized == "status":

        show_status(agent)
        return False

    if normalized == "memory":

        show_memory(agent)
        return False

    if normalized == "help":

        show_help()
        return False

    if normalized == "clear-history":

        clear_history(agent)
        return False

    return False


def main() -> int:

    try:

        agent = ALIXAgent()

    except Exception as exc:

        print(
            "❌ فشل تشغيل ALIX."
        )

        print(
            f"السبب: {exc}"
        )

        return 1

    print_banner(agent)

    while True:

        try:

            user_input = input(
                "\n👤 أنت: "
            ).strip()

        except KeyboardInterrupt:

            print(
                "\n\n👋 تم إيقاف ALIX."
            )

            return 0

        except EOFError:

            print(
                "\n\n👋 تم إغلاق الإدخال."
            )

            return 0

        except Exception as exc:

            print(
                f"\n❌ خطأ في واجهة الإدخال: {exc}"
            )

            continue

        if not user_input:
            continue

        if user_input.lower() in {
            "exit",
            "quit",
            "خروج"
        }:

            print(
                "\n👋 إلى اللقاء."
            )

            return 0

        # أوامر الواجهة.
        if user_input.lower() in {
            "status",
            "memory",
            "help",
            "clear-history"
        }:

            handle_special_command(
                user_input,
                agent
            )

            continue

        print(
            "\n⏳ ALIX يحلل الطلب..."
        )

        try:

            response = agent.run(
                user_input
            )

            print(
                "\n🤖 ALIX:"
            )

            print(
                response
            )

        except KeyboardInterrupt:

            print(
                "\n⚠️ تم إلغاء العملية الحالية."
            )

        except Exception as exc:

            print(
                "\n❌ حدث خطأ غير متوقع أثناء تشغيل ALIX:"
            )

            print(
                str(exc)
            )

            # لا نعرض Traceback للمستخدم العادي.
            try:

                agent.audit(
                    "main_exception",
                    {
                        "error": str(exc)
                    }
                )

            except Exception:
                pass


if __name__ == "__main__":

    sys.exit(
        main()
    )
