from core.policy import Policy
from core.registry import ToolRegistry
from core.llm import LocalLLM


SYSTEM_PROMPT = """
أنت ALIX Local.

أنت وكيل ذكاء اصطناعي محلي يعمل داخل Termux.

قواعدك:

1. أجب بالعربية.
2. لا تعرض التفكير الداخلي.
3. لا تدّعي تنفيذ شيء لم يتم تنفيذه فعليًا.
4. عندما تحتاج إلى أداة، استخدم الأداة المناسبة.
5. استخدم مساحة ALIX فقط للملفات.
6. لا تحاول الوصول إلى ملفات نظام Android.
7. لا تنفذ أوامر خطرة.
8. بعد تنفيذ الأداة، اقرأ النتيجة ثم أجب المستخدم.
9. إذا لم تعرف شيئًا، قل: لا أعرف.
"""


class ALIXAgent:

    def __init__(self):

        self.policy = Policy()

        self.registry = ToolRegistry(
            self.policy
        )

        self.llm = LocalLLM()

        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

    def run(self, user):

        self.messages.append({
            "role": "user",
            "content": user
        })

        message = self.llm.chat(
            self.messages
        )

        content = message.get(
            "content",
            ""
        )

        self.messages.append({
            "role": "assistant",
            "content": content
        })

        return content
