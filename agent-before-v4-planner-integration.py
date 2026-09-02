import os
import json
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
import memory_manager

# ============================================================
# ALIX AI AGENT V3
# Real Local Tool Calling
# ============================================================

BASE_DIR = Path.home() / "ALIX-Agent"
REAL_MEMORY_FILE = BASE_DIR / "memory" / "memory.json"
MEMORY_DIR = BASE_DIR / "memory"
LOG_DIR = BASE_DIR / "logs"

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY غير موجود في .env")

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

MODEL = "openai/gpt-oss-120b"

MAX_TOOL_ROUNDS = 8


# ============================================================
# MEMORY
# ============================================================

def load_memory():
    return memory_manager.load_memory(REAL_MEMORY_FILE)


def save_memory(memory):
    memory_manager.save_memory(
        memory,
        REAL_MEMORY_FILE
    )


# ============================================================
# SECURITY
# ============================================================

DANGEROUS_PATTERNS = [
    "rm -rf",
    "rm -r /",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "poweroff",
    "iptables -F",
    "nft flush",
    "chmod -R 777",
    "chown -R",
    "passwd",
    "userdel",
    "pkill -9",
]


def dangerous(command):

    command_lower = command.lower()

    return any(
        pattern.lower() in command_lower
        for pattern in DANGEROUS_PATTERNS
    )


# ============================================================
# TOOL: LIST FILES
# ============================================================

def list_files(path="."):

    try:
        p = Path(path).expanduser()

        if not p.exists():
            return {
                "success": False,
                "error": "المسار غير موجود"
            }

        if p.is_file():
            return {
                "success": True,
                "type": "file",
                "path": str(p)
            }

        items = []

        for item in sorted(p.iterdir()):

            items.append({
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file"
            })

        return {
            "success": True,
            "path": str(p),
            "items": items[:300]
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL: READ FILE
# ============================================================

def read_file(path):

    try:

        p = Path(path).expanduser()

        if not p.exists():
            return {
                "success": False,
                "error": "الملف غير موجود"
            }

        if not p.is_file():
            return {
                "success": False,
                "error": "المسار ليس ملفًا"
            }

        size = p.stat().st_size

        if size > 2_000_000:
            return {
                "success": False,
                "error": "الملف أكبر من 2MB"
            }

        content = p.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return {
            "success": True,
            "path": str(p),
            "content": content[:40000]
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL: SEARCH FILES
# ============================================================

def search_files(path, pattern):

    try:

        root = Path(path).expanduser()

        if not root.exists():
            return {
                "success": False,
                "error": "المجلد غير موجود"
            }

        matches = []

        for p in root.rglob("*"):

            if len(matches) >= 200:
                break

            if p.is_file() and pattern.lower() in p.name.lower():

                matches.append(str(p))

        return {
            "success": True,
            "matches": matches
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL: WRITE FILE
# ============================================================

def write_file(path, content):

    p = Path(path).expanduser()

    print("\n╭────────────────────────────────────╮")
    print("│       FILE WRITE REQUEST           │")
    print("╰────────────────────────────────────╯")

    print(f"File: {p}")
    print(f"Size: {len(content)} bytes")

    answer = input(
        "هل تسمح لـ ALIX بكتابة هذا الملف؟ [y/N]: "
    ).strip().lower()

    if answer != "y":

        return {
            "success": False,
            "error": "المستخدم رفض كتابة الملف"
        }

    try:

        p.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        p.write_text(
            content,
            encoding="utf-8"
        )

        return {
            "success": True,
            "message": f"تم حفظ الملف {p}"
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL: RUN TERMINAL
# ============================================================

def run_terminal(command):

    print("\n╭────────────────────────────────────╮")
    print("│       TERMINAL EXECUTION           │")
    print("╰────────────────────────────────────╯")

    print(command)

    if dangerous(command):

        print("\n🚨 تحذير: هذا الأمر مصنف كأمر خطير.")

        answer = input(
            "اكتب ALIX-YES للتأكيد: "
        ).strip()

        if answer != "ALIX-YES":

            return {
                "success": False,
                "error": "تم رفض الأمر الخطير"
            }

    else:

        answer = input(
            "هل تسمح لـ ALIX بتنفيذ الأمر؟ [y/N]: "
        ).strip().lower()

        if answer != "y":

            return {
                "success": False,
                "error": "المستخدم رفض التنفيذ"
            }

    try:

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )

        return {
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout[:20000],
            "stderr": result.stderr[:10000]
        }

    except subprocess.TimeoutExpired:

        return {
            "success": False,
            "error": "انتهت مهلة التنفيذ"
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL SCHEMAS
# ============================================================

TOOLS = [

    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files and directories inside a path. "
                "Use this when you need to inspect a project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to inspect"
                    }
                },
                "required": ["path"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a text file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path"
                    }
                },
                "required": ["path"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search for files by filename inside a directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "pattern": {
                        "type": "string"
                    }
                },
                "required": ["path", "pattern"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a text file. "
                "Always requires user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "content": {
                        "type": "string"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "save_fact",
            "description": (
                "Save or update a non-sensitive fact in ALIX persistent memory. "
                "Do not use for API keys, passwords, tokens, secrets, or credentials."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string"
                    },
                    "value": {
                        "type": "string"
                    }
                },
                "required": ["key", "value"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "get_fact",
            "description": (
                "Retrieve a previously saved fact from ALIX persistent memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string"
                    }
                },
                "required": ["key"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "save_preference",
            "description": (
                "Save or update a non-sensitive user preference in persistent memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string"
                    },
                    "value": {
                        "type": "string"
                    }
                },
                "required": ["key", "value"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "get_preference",
            "description": (
                "Retrieve a previously saved preference from persistent memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string"
                    }
                },
                "required": ["key"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "memory_summary",
            "description": (
                "Return counts of facts, preferences, and history in persistent memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": (
                "Execute a Termux shell command. "
                "Requires explicit user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


# ============================================================
# TOOL DISPATCHER
# ============================================================

def execute_tool(name, arguments):

    if name == "list_files":
        return list_files(
            arguments.get("path", ".")
        )

    if name == "read_file":
        return read_file(
            arguments["path"]
        )

    if name == "search_files":
        return search_files(
            arguments["path"],
            arguments["pattern"]
        )

    if name == "write_file":
        return write_file(
            arguments["path"],
            arguments["content"]
        )

    if name == "save_fact":
        return {
            "success": memory_manager.add_fact(
                arguments["key"],
                arguments["value"],
                REAL_MEMORY_FILE
            ),
            "key": arguments["key"]
        }

    if name == "get_fact":
        value = memory_manager.get_fact(
            arguments["key"],
            REAL_MEMORY_FILE
        )

        return {
            "success": value is not None,
            "key": arguments["key"],
            "value": value
        }

    if name == "save_preference":
        return {
            "success": memory_manager.add_preference(
                arguments["key"],
                arguments["value"],
                REAL_MEMORY_FILE
            ),
            "key": arguments["key"]
        }

    if name == "get_preference":
        value = memory_manager.get_preference(
            arguments["key"],
            REAL_MEMORY_FILE
        )

        return {
            "success": value is not None,
            "key": arguments["key"],
            "value": value
        }

    if name == "memory_summary":
        return {
            "success": True,
            "summary": memory_manager.get_summary(
                REAL_MEMORY_FILE
            )
        }

    if name == "run_terminal":
        return run_terminal(
            arguments["command"]
        )

    return {
        "success": False,
        "error": f"Unknown tool: {name}"
    }


# ============================================================
# AGENT LOOP
# ============================================================

def run_agent(user_input):

    memory = load_memory()


    messages = [

        {
            "role": "system",
            "content": """
أنت ALIX V3، AI Agent شخصي يعمل داخل Termux على Android.

أنت قادر على استخدام أدوات محلية حقيقية.

الأدوات المتاحة:

- list_files
- read_file
- search_files
- write_file
- run_terminal
- save_fact
- get_fact
- save_preference
- get_preference
- memory_summary

قواعد مهمة:

1. استخدم الأدوات عندما تكون ضرورية.
2. لا تدّعي أنك قرأت ملفًا إلا إذا استخدمت read_file.
3. لا تدّعي أنك نفذت أمرًا إلا إذا أعادت أداة run_terminal نتيجة.
4. قبل تعديل الملفات سيطلب البرنامج موافقة المستخدم.
5. قبل تنفيذ أوامر Terminal سيطلب البرنامج موافقة المستخدم.
6. لا تحاول تجاوز نظام الموافقة.
7. لا تكشف API keys أو محتويات ملفات الأسرار.
8. لا تقرأ .env إلا إذا طلب المستخدم ذلك صراحة.
9. إذا وجدت خطأ في مشروع، اجمع الأدلة أولًا ثم اقترح الإصلاح.
10. استخدم العربية عندما يتحدث المستخدم بالعربية.
11. لا تنفذ إجراءات خطيرة دون التأكيد الإضافي.
12. عند طلب المستخدم حفظ Fact، استخدم save_fact فعليًا.
13. عند طلب المستخدم حفظ Preference، استخدم save_preference فعليًا.
14. لا تقل إن معلومة تم حفظها في الذاكرة إلا إذا أعادت أداة الذاكرة success=true.
15. عند طلب استرجاع Fact أو Preference، استخدم أداة الذاكرة المناسبة بدل التخمين.
16. لا تحفظ API keys أو كلمات المرور أو tokens أو الأسرار؛ أدوات الذاكرة تمنع ذلك.
17. الذاكرة الدائمة موجودة في memory.json وتدار بواسطة memory_manager.py.
"""
        }
    ]

    # ========================================================
    # MEMORY V4 CONTEXT
    # ========================================================

    facts = memory.get("facts", [])
    preferences = memory.get("preferences", [])

    memory_context = []

    if facts:
        memory_context.append("FACTS:")
        for fact in facts:
            if isinstance(fact, dict):
                key = fact.get("key", "")
                value = fact.get("value", "")
                memory_context.append(
                    f"- {key}: {value}"
                )

    if preferences:
        memory_context.append("PREFERENCES:")
        for preference in preferences:
            if isinstance(preference, dict):
                key = preference.get("key", "")
                value = preference.get("value", "")
                memory_context.append(
                    f"- {key}: {value}"
                )

    if memory_context:
        messages.append({
            "role": "system",
            "content": (
                "هذه معلومات الذاكرة الدائمة الموثوقة لـ ALIX. "
                "استخدمها كمرجع، ولا تخترع معلومات غير موجودة فيها.\n\n"
                + "\n".join(memory_context)
            )
        })

    # Add recent memory
    for item in memory["history"][-8:]:

        messages.append({
            "role": "user",
            "content": item.get("user", "")
        })

        messages.append({
            "role": "assistant",
            "content": item.get("assistant", "")
        })

    messages.append({
        "role": "user",
        "content": user_input
    })



# ============================================================
# AUTO MEMORY — AGENTIC MEMORY V5
# ============================================================

    # ========================================================
    # AGENTIC LOOP
    # ========================================================

    for round_number in range(MAX_TOOL_ROUNDS):

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                reasoning_effort="medium",
                max_completion_tokens=6000
            )

        except Exception as e:
            return f"❌ OpenRouter API error:\n{e}"

        message = response.choices[0].message

        # ----------------------------------------------------
        # No tool call = final answer
        # ----------------------------------------------------

        if not message.tool_calls:
            return message.content or "لم يرجع النموذج إجابة."

        # ----------------------------------------------------
        # Add assistant tool-call message
        # ----------------------------------------------------

        messages.append(message)

        # ----------------------------------------------------
        # Execute requested tools
        # ----------------------------------------------------

        for tool_call in message.tool_calls:

            name = tool_call.function.name

            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )

            except json.JSONDecodeError:

                result = {
                    "success": False,
                    "error": "Invalid JSON tool arguments"
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(
                        result,
                        ensure_ascii=False
                    )
                })

                continue

            print(f"\n🔧 ALIX يستخدم الأداة: {name}")

            result = execute_tool(
                name,
                arguments
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": json.dumps(
                    result,
                    ensure_ascii=False
                )
            })

    return "⚠️ وصلت إلى الحد الأقصى من خطوات الأدوات."



# ============================================================
# ALIX V4 — SAFE PLANNER
# ============================================================

def create_plan(user_input):
    """
    Creates a simple execution plan without executing tools.

    This function is intentionally isolated from the Agentic Loop.
    It only analyzes the request and returns ordered steps.
    """

    if not isinstance(user_input, str):
        return []

    text = user_input.strip()

    if not text:
        return []

    steps = []

    # File/project inspection
    if any(word in text.lower() for word in [
        "افحص", "تحقق", "inspect", "check", "analyze", "حلل"
    ]):
        steps.append("فحص المشروع وجمع الأدلة أولًا")

    # Reading
    if any(word in text.lower() for word in [
        "اقرأ", "قراءة", "read", "عرض الملف"
    ]):
        steps.append("قراءة الملفات المطلوبة باستخدام read_file")

    # Searching
    if any(word in text.lower() for word in [
        "ابحث", "بحث", "search", "find"
    ]):
        steps.append("البحث عن الملفات أو الأنماط المطلوبة")

    # Writing/modification
    if any(word in text.lower() for word in [
        "أنشئ", "اكتب", "عدّل", "تعديل", "اصلح", "إصلاح",
        "create", "write", "modify", "fix"
    ]):
        steps.append("اقتراح أو تنفيذ التعديل بعد الحصول على الموافقة المطلوبة")

    # Terminal
    if any(word in text.lower() for word in [
        "terminal", "ترمنل", "أمر", "command"
    ]):
        steps.append("تنفيذ أمر Terminal فقط بعد موافقة المستخدم")

    # Generic plan
    if not steps:
        steps.append("تحليل الطلب وتحديد الأداة المناسبة")

    steps.append("التحقق من النتيجة قبل تقديم الإجابة النهائية")

    return steps

    # ========================================================
    # AGENTIC LOOP
    # ========================================================

    for round_number in range(MAX_TOOL_ROUNDS):

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                reasoning_effort="medium",
                max_completion_tokens=6000
            )

        except Exception as e:
            return f"❌ OpenRouter API error:\n{e}"

        message = response.choices[0].message

        # ----------------------------------------------------
        # No tool call = final answer
        # ----------------------------------------------------

        if not message.tool_calls:
            return message.content or "لم يرجع النموذج إجابة."

        # ----------------------------------------------------
        # Add assistant tool-call message
        # ----------------------------------------------------

        messages.append(message)

        # ----------------------------------------------------
        # Execute requested tools
        # ----------------------------------------------------

        for tool_call in message.tool_calls:

            name = tool_call.function.name

            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )

            except json.JSONDecodeError:

                result = {
                    "success": False,
                    "error": "Invalid JSON tool arguments"
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(
                        result,
                        ensure_ascii=False
                    )
                })

                continue

            print(f"\n🔧 ALIX يستخدم الأداة: {name}")

            result = execute_tool(
                name,
                arguments
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": json.dumps(
                    result,
                    ensure_ascii=False
                )
            })

    return "⚠️ وصلت إلى الحد الأقصى من خطوات الأدوات."

def detect_memory_intent(user_input):
    """
    Detect durable user preferences/facts without using Terminal.
    Returns None, or:
    {"type": "preference", "key": ..., "value": ...}
    {"type": "fact", "key": ..., "value": ...}
    """

    if not isinstance(user_input, str):
        return None

    text = user_input.strip()

    if not text:
        return None

    # Explicitly durable preference language.
    preference_patterns = [
        (r"من الآن فصاعدًا.*?أريدك أن (.+)", "user_preference"),
        (r"من الآن فصاعدًا.*?أفضل أن (.+)", "user_preference"),
        (r"دائمًا.*?أريدك أن (.+)", "user_preference"),
        (r"always.*?prefer (.+)", "user_preference"),
        (r"from now on.*?I want you to (.+)", "user_preference"),
    ]

    for pattern, key in preference_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = m.group(1).strip()

            if memory_manager.contains_secret(value):
                return None

            return {
                "type": "preference",
                "key": key,
                "value": value
            }

    return None


def auto_save_memory(user_input):
    """
    Save only clearly durable preferences.
    Never saves secrets.
    """
    intent = detect_memory_intent(user_input)

    if not intent:
        return False

    if intent["type"] == "preference":
        return memory_manager.add_preference(
            intent["key"],
            intent["value"],
            REAL_MEMORY_FILE
        )

    if intent["type"] == "fact":
        return memory_manager.add_fact(
            intent["key"],
            intent["value"],
            REAL_MEMORY_FILE
        )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("""
╔══════════════════════════════════════╗
║          ALIX AI AGENT V3            ║
║       REAL TOOL-CALLING AGENT        ║
╠══════════════════════════════════════╣
║ OpenRouter GPT-OSS-120B                    ║
║ Local File Tools                     ║
║ Local Terminal Tool                  ║
║ Persistent Memory                    ║
║ Security Confirmation                ║
╚══════════════════════════════════════╝

ALIX يستطيع الآن اختيار الأدوات بنفسه.

أمثلة:

"اعرض لي ملفات هذا المشروع"

"اقرأ main.py"

"ابحث عن ملفات Python"

"افحص المشروع واكتشف الخطأ"

"أنشئ ملف test.py"

سيطلب ALIX موافقتك قبل الكتابة أو تنفيذ أوامر Terminal.

للخروج:
exit
""")


    while True:

        try:

            user_input = input("\n👤 أنت: ").strip()

        except KeyboardInterrupt:

            print("\n👋 تم إيقاف ALIX.")
            break

        except EOFError:

            break


        if not user_input:
            continue


        if user_input.lower() in [
            "exit",
            "quit",
            "خروج"
        ]:

            print("\n👋 إلى اللقاء.")
            break


        print("\n⏳ ALIX يفكر...")


        response = run_agent(
            user_input
        )


        print("\n🤖 ALIX:")
        print(response)


        memory_manager.add_history(
            user_input,
            response,
            REAL_MEMORY_FILE
        )


if __name__ == "__main__":
    main()
