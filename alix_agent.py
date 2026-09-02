#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
                    ALIX LOCAL AGENT v2
             Qwen 3.5 4B + llama.cpp + Termux
============================================================

Architecture:

User
  ↓
ALIX Controller
  ↓
Qwen / llama.cpp
  ↓
Tool Call
  ↓
Permission + Security
  ↓
Tool Execution
  ↓
Result → Qwen
  ↓
Next Tool / Final Answer

Workspace:
    ~/ALIX-Agent/workspace

Logs:
    ~/ALIX-Agent/logs

API:
    http://127.0.0.1:8081/v1/chat/completions

No external Python packages are required.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path.home() / "ALIX-Agent"

WORKSPACE = BASE_DIR / "workspace"
LOG_DIR = BASE_DIR / "logs"

API_URL = os.environ.get(
    "ALIX_API",
    "http://127.0.0.1:8081/v1/chat/completions"
)

MODEL = os.environ.get(
    "ALIX_MODEL",
    "Qwen3.5-4B-Instruct-Q4_K_M.gguf"
)

MAX_AGENT_TURNS = 8
MAX_TOOL_CALLS_PER_TURN = 4

MAX_FILE_READ = 2 * 1024 * 1024
MAX_FILE_WRITE = 2 * 1024 * 1024

MODEL_TIMEOUT = 180
COMMAND_TIMEOUT = 60


# ============================================================
# INITIALIZE DIRECTORIES
# ============================================================

BASE_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
أنت ALIX Local، وكيل ذكاء اصطناعي محلي يعمل داخل Termux.

قواعد أساسية:

1. أجب بالعربية عندما يكون ذلك مناسباً.
2. أجب مباشرة وبوضوح.
3. لا تعرض خطوات التفكير الداخلي أو التحليل الداخلي.
4. لا تخترع نتائج.
5. عندما تحتاج إلى تنفيذ عملية، استخدم الأدوات المتاحة.
6. لا تدّعي أنك نفذت عملية إذا لم تُرجع الأداة نجاحاً.
7. جميع عمليات الملفات يجب أن تكون داخل workspace.
8. لا تحاول الوصول إلى ملفات نظام Android.
9. لا تستخدم sudo أو su.
10. لا تحذف ملفات خارج workspace.
11. لا تنفذ أوامر خطيرة.
12. بعد تنفيذ الأداة، اقرأ النتيجة واستخدمها في الخطوة التالية.
13. إذا فشلت عملية، حاول تصحيح الخطأ عندما يكون ذلك آمناً.
14. عندما تنتهي المهمة، أعط المستخدم النتيجة النهائية فقط.

عند الحاجة إلى أداة استخدم tool calling الخاص بالـAPI.

لا تكتب استدعاء الأداة كنص إذا كان API يستطيع إرسال tool call حقيقي.
"""


# ============================================================
# TOOL DEFINITIONS
# ============================================================

TOOLS = [

    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "عرض الملفات والمجلدات داخل workspace أو داخله."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "مسار نسبي داخل workspace. الافتراضي ."
                    },
                    "all": {
                        "type": "boolean",
                        "description": "عرض الملفات المخفية أيضاً."
                    }
                },
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "إنشاء مجلد داخل workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
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
            "description": "قراءة ملف نصي داخل workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    }
                },
                "required": ["path"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "إنشاء أو استبدال ملف نصي داخل workspace.",
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
            "name": "delete_file",
            "description": "حذف ملف واحد داخل workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    }
                },
                "required": ["path"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "تشغيل ملف Python موجود داخل workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "args": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "required": ["path"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "عرض حالة Git لمشروع داخل workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    }
                },
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "تشغيل أمر shell مسموح به داخل workspace. "
                "الأوامر الخطرة أو التي تستخدم shell chaining ممنوعة."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string"
                    },
                    "timeout": {
                        "type": "integer"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


# ============================================================
# TOOL POLICY
# ============================================================

READ_ONLY_TOOLS = {
    "list_files",
    "read_file",
    "git_status",
}


# أوامر نسمح بها داخل workspace فقط.
# يمكن توسيعها لاحقاً.
ALLOWED_COMMANDS = {
    "ls",
    "pwd",
    "find",
    "cat",
    "head",
    "tail",
    "grep",
    "printf",
    "echo",
    "wc",
    "sort",
    "uniq",
    "cut",
    "tr",
    "mkdir",
    "touch",
    "cp",
    "mv",
    "python",
    "python3",
    "git",
    "pip",
    "pip3",
    "which",
    "file",
    "du",
    "df",
}


FORBIDDEN_COMMAND_PATTERNS = [

    r"\bsudo\b",
    r"\bsu\b",

    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",

    r"\bmkfs\b",
    r"\bdd\s+if=",

    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",

    r"\bmount\b",
    r"\bumount\b",

    r"\biptables\b",
    r"\bip6tables\b",

    r"\bchmod\s+777\b",
    r"\bchown\b",

    r"\btermux-change-repo\b",

    r">\s*/",
    r">>\s*/",

    r"\b/etc/\b",
    r"\b/proc/\b",
    r"\b/sys/\b",
    r"\b/dev/\b",
    r"\b/data/data/\b",

    r"\bcurl\b.*\|\s*(bash|sh)",
    r"\bwget\b.*\|\s*(bash|sh)",

    r"\beval\b",
    r"\bexec\b",

    r":\(\)\s*\{",

    r"\$\(",
    r"`",

    r";",
    r"\|\|",
    r"&&",
    r"\|",
    r"<",
    r">",
]


# ============================================================
# LOGGING
# ============================================================

def log_event(event, data=None):

    try:

        log_file = LOG_DIR / "agent.log"

        record = {
            "event": event,
            "data": data,
        }

        with log_file.open(
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                ) + "\n"
            )

    except Exception:
        pass


# ============================================================
# SAFE PATH
# ============================================================

def safe_path(user_path):

    if not isinstance(user_path, str):
        raise ValueError("المسار غير صالح.")

    user_path = user_path.strip()

    if not user_path:
        user_path = "."

    candidate = (
        WORKSPACE / user_path
    ).resolve()

    root = WORKSPACE.resolve()

    if candidate != root and root not in candidate.parents:

        raise PermissionError(
            "ممنوع الوصول خارج workspace."
        )

    return candidate


# ============================================================
# COMMAND SECURITY
# ============================================================

def command_is_forbidden(command):

    if not isinstance(command, str):
        return True

    command = command.strip()

    if not command:
        return True

    for pattern in FORBIDDEN_COMMAND_PATTERNS:

        if re.search(
            pattern,
            command,
            flags=re.IGNORECASE
        ):

            return True

    return False


def command_is_allowed(command):

    if command_is_forbidden(command):
        return False

    try:

        parts = shlex.split(command)

    except ValueError:
        return False

    if not parts:
        return False

    executable = Path(parts[0]).name

    return executable in ALLOWED_COMMANDS


# ============================================================
# USER PERMISSION
# ============================================================

def ask_permission(tool_name, arguments):

    print()
    print("ALIX يريد تنفيذ:")

    if tool_name == "create_directory":

        print(
            "  📁 إنشاء مجلد:",
            arguments.get("path")
        )

    elif tool_name == "write_file":

        print(
            "  📝 كتابة ملف:",
            arguments.get("path")
        )

    elif tool_name == "delete_file":

        print(
            "  🗑 حذف ملف:",
            arguments.get("path")
        )

    elif tool_name == "run_python":

        print(
            "  🐍 تشغيل Python:",
            arguments.get("path")
        )

    elif tool_name == "run_command":

        print(
            "  $",
            arguments.get("command")
        )

    else:

        print(
            " ",
            tool_name,
            json.dumps(
                arguments,
                ensure_ascii=False
            )
        )

    answer = input(
        "هل تريد السماح لـ ALIX بتنفيذ هذا الإجراء؟ [y/N] "
    ).strip().lower()

    return answer in {
        "y",
        "yes",
        "نعم",
        "ن"
    }


# ============================================================
# TOOL: LIST FILES
# ============================================================

def tool_list_files(arguments):

    path = safe_path(
        arguments.get("path", ".")
    )

    include_hidden = bool(
        arguments.get("all", False)
    )

    if not path.exists():

        return {
            "ok": False,
            "error": "المجلد غير موجود."
        }

    if not path.is_dir():

        return {
            "ok": False,
            "error": "المسار ليس مجلداً."
        }

    result = []

    for item in sorted(
        path.iterdir(),
        key=lambda x: (
            not x.is_dir(),
            x.name.lower()
        )
    ):

        if (
            not include_hidden
            and item.name.startswith(".")
        ):
            continue

        try:

            size = (
                item.stat().st_size
                if item.is_file()
                else None
            )

        except Exception:

            size = None

        result.append(
            {
                "name": item.name,
                "type": (
                    "directory"
                    if item.is_dir()
                    else "file"
                ),
                "size": size,
            }
        )

    return {
        "ok": True,
        "path": str(
            path.relative_to(WORKSPACE)
        ) or ".",
        "items": result[:500],
    }


# ============================================================
# TOOL: CREATE DIRECTORY
# ============================================================

def tool_create_directory(arguments):

    path = safe_path(
        arguments["path"]
    )

    path.mkdir(
        parents=True,
        exist_ok=True
    )

    return {
        "ok": True,
        "created": str(
            path.relative_to(WORKSPACE)
        )
    }


# ============================================================
# TOOL: READ FILE
# ============================================================

def tool_read_file(arguments):

    path = safe_path(
        arguments["path"]
    )

    if not path.exists():

        return {
            "ok": False,
            "error": "الملف غير موجود."
        }

    if not path.is_file():

        return {
            "ok": False,
            "error": "المسار ليس ملفاً."
        }

    if path.stat().st_size > MAX_FILE_READ:

        return {
            "ok": False,
            "error": "الملف أكبر من الحد المسموح."
        }

    content = path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    return {
        "ok": True,
        "path": str(
            path.relative_to(WORKSPACE)
        ),
        "content": content,
    }


# ============================================================
# TOOL: WRITE FILE
# ============================================================

def tool_write_file(arguments):

    path = safe_path(
        arguments["path"]
    )

    content = arguments.get(
        "content",
        ""
    )

    encoded = content.encode(
        "utf-8"
    )

    if len(encoded) > MAX_FILE_WRITE:

        return {
            "ok": False,
            "error": "المحتوى أكبر من الحد المسموح."
        }

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        content,
        encoding="utf-8"
    )

    return {
        "ok": True,
        "written": str(
            path.relative_to(WORKSPACE)
        ),
        "bytes": len(encoded),
    }


# ============================================================
# TOOL: DELETE FILE
# ============================================================

def tool_delete_file(arguments):

    path = safe_path(
        arguments["path"]
    )

    if not path.exists():

        return {
            "ok": False,
            "error": "الملف غير موجود."
        }

    if path.is_dir():

        return {
            "ok": False,
            "error": (
                "حذف المجلدات غير مسموح "
                "بهذه الأداة."
            )
        }

    path.unlink()

    return {
        "ok": True,
        "deleted": str(
            path.relative_to(WORKSPACE)
        )
    }


# ============================================================
# TOOL: RUN PYTHON
# ============================================================

def tool_run_python(arguments):

    path = safe_path(
        arguments["path"]
    )

    if path.suffix != ".py":

        return {
            "ok": False,
            "error": "يجب أن يكون الملف Python (.py)."
        }

    if not path.is_file():

        return {
            "ok": False,
            "error": "ملف Python غير موجود."
        }

    user_args = arguments.get(
        "args",
        []
    )

    if not isinstance(
        user_args,
        list
    ):

        return {
            "ok": False,
            "error": "args يجب أن تكون قائمة."
        }

    command = [
        sys.executable,
        str(path),
    ] + [
        str(x)
        for x in user_args
    ]

    try:

        result = subprocess.run(
            command,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    except subprocess.TimeoutExpired:

        return {
            "ok": False,
            "error": (
                "انتهت مهلة تشغيل Python."
            )
        }


# ============================================================
# TOOL: GIT STATUS
# ============================================================

def tool_git_status(arguments):

    path = safe_path(
        arguments.get("path", ".")
    )

    try:

        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "status",
                "--short",
                "--branch",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-4000:],
        }

    except Exception as e:

        return {
            "ok": False,
            "error": str(e)
        }


# ============================================================
# TOOL: RUN COMMAND
# ============================================================

def tool_run_command(arguments):

    command = arguments.get(
        "command",
        ""
    ).strip()

    if not command:

        return {
            "ok": False,
            "error": "الأمر فارغ."
        }

    if not command_is_allowed(command):

        return {
            "ok": False,
            "error": (
                "الأمر غير مسموح به "
                "بواسطة سياسة ALIX."
            )
        }

    try:

        timeout = int(
            arguments.get(
                "timeout",
                30
            )
        )

    except Exception:

        timeout = 30

    timeout = max(
        1,
        min(timeout, COMMAND_TIMEOUT)
    )

    try:

        result = subprocess.run(
            [
                "bash",
                "-lc",
                command
            ],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    except subprocess.TimeoutExpired:

        return {
            "ok": False,
            "error": (
                f"انتهت المهلة بعد {timeout} ثانية."
            )
        }


# ============================================================
# TOOL DISPATCH
# ============================================================

TOOL_DISPATCH = {

    "list_files":
        tool_list_files,

    "create_directory":
        tool_create_directory,

    "read_file":
        tool_read_file,

    "write_file":
        tool_write_file,

    "delete_file":
        tool_delete_file,

    "run_python":
        tool_run_python,

    "git_status":
        tool_git_status,

    "run_command":
        tool_run_command,
}


# ============================================================
# MODEL REQUEST
# ============================================================

def call_model(messages):

    payload = {

        "model": MODEL,

        "messages": messages,

        "tools": TOOLS,

        "tool_choice": "auto",

        "temperature": 0.2,

        "max_tokens": 700,
    }

    body = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(

        API_URL,

        data=body,

        headers={
            "Content-Type":
                "application/json"
        },

        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=MODEL_TIMEOUT
        ) as response:

            raw = response.read()

        return json.loads(
            raw.decode("utf-8")
        )

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"llama.cpp HTTP {e.code}: "
            f"{error_body[:2000]}"
        )

    except Exception as e:

        raise RuntimeError(
            f"تعذر الاتصال بـ llama.cpp: {e}"
        )


# ============================================================
# TOOL CALL PARSER
# ============================================================

def extract_tool_calls(message):

    calls = []

    # --------------------------------------------------------
    # Native OpenAI-compatible tool calls
    # --------------------------------------------------------

    native_calls = (
        message.get("tool_calls")
        or []
    )

    for call in native_calls:

        function = call.get(
            "function",
            {}
        )

        name = function.get(
            "name"
        )

        arguments = function.get(
            "arguments",
            "{}"
        )

        if isinstance(
            arguments,
            str
        ):

            try:

                arguments = json.loads(
                    arguments
                )

            except Exception:

                continue

        if not isinstance(
            arguments,
            dict
        ):

            continue

        if name:

            calls.append(
                (
                    call.get(
                        "id",
                        f"call-{len(calls)}"
                    ),
                    name,
                    arguments
                )
            )

    # --------------------------------------------------------
    # Fallback: <tool_call>{...}</tool_call>
    # --------------------------------------------------------

    content = message.get(
        "content",
        ""
    ) or ""

    pattern = (
        r"<tool_call>\s*"
        r"(\{.*?\})"
        r"\s*</tool_call>"
    )

    for match in re.finditer(
        pattern,
        content,
        flags=re.DOTALL
    ):

        try:

            obj = json.loads(
                match.group(1)
            )

            name = obj.get(
                "name"
            )

            arguments = obj.get(
                "arguments",
                {}
            )

            if name:

                calls.append(
                    (
                        f"tag-{len(calls)}",
                        name,
                        arguments
                    )
                )

        except Exception:

            continue

    return calls


# ============================================================
# CLEAN MODEL TEXT
# ============================================================

def clean_response(text):

    if not text:

        return ""

    # إزالة tool tags إذا بقيت في النص.
    text = re.sub(
        r"<tool_call>.*?</tool_call>",
        "",
        text,
        flags=re.DOTALL
    )

    # لا نعرض reasoning tags.
    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL
    )

    return text.strip()


# ============================================================
# EXECUTE ONE TOOL
# ============================================================

def execute_tool(
    call_id,
    tool_name,
    arguments
):

    if tool_name not in TOOL_DISPATCH:

        return {
            "ok": False,
            "error": (
                f"الأداة غير معروفة: "
                f"{tool_name}"
            )
        }

    if not isinstance(
        arguments,
        dict
    ):

        return {
            "ok": False,
            "error": "arguments غير صالحة."
        }

    # --------------------------------------------------------
    # Security pre-check
    # --------------------------------------------------------

    if tool_name == "run_command":

        command = arguments.get(
            "command",
            ""
        )

        if not command_is_allowed(
            command
        ):

            return {
                "ok": False,
                "error": (
                    "تم رفض الأمر "
                    "بواسطة سياسة الأمان."
                )
            }

    # --------------------------------------------------------
    # Permission
    # --------------------------------------------------------

    if tool_name not in READ_ONLY_TOOLS:

        if not ask_permission(
            tool_name,
            arguments
        ):

            print("⏭ تم رفض التنفيذ.")

            return {
                "ok": False,
                "error": (
                    "المستخدم رفض التنفيذ."
                )
            }

    # --------------------------------------------------------
    # Execute
    # --------------------------------------------------------

    try:

        print(
            f"⚙ تنفيذ الأداة: {tool_name}"
        )

        result = TOOL_DISPATCH[
            tool_name
        ](arguments)

        if result.get("ok"):

            print(
                "✓ تم التنفيذ بنجاح"
            )

        else:

            print(
                "✗ فشل التنفيذ"
            )

        log_event(
            "tool_execution",
            {
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            }
        )

        return result

    except Exception as e:

        error = {
            "ok": False,
            "error": str(e)
        }

        log_event(
            "tool_error",
            {
                "tool": tool_name,
                "error": str(e),
            }
        )

        print(
            f"✗ خطأ: {e}"
        )

        return error


# ============================================================
# AGENT LOOP
# ============================================================

def run_agent(user_input):

    messages = [

        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },

        {
            "role": "user",
            "content": user_input
        },
    ]

    for turn in range(
        MAX_AGENT_TURNS
    ):

        log_event(
            "model_request",
            {
                "turn": turn
            }
        )

        response = call_model(
            messages
        )

        choices = response.get(
            "choices",
            []
        )

        if not choices:

            return (
                "لم يرجع النموذج أي نتيجة."
            )

        message = choices[0].get(
            "message",
            {}
        )

        tool_calls = extract_tool_calls(
            message
        )

        # ----------------------------------------------------
        # Final answer
        # ----------------------------------------------------

        if not tool_calls:

            answer = clean_response(
                message.get(
                    "content",
                    ""
                )
            )

            if answer:

                return answer

            return (
                "لم يرجع النموذج إجابة نصية."
            )

        # ----------------------------------------------------
        # Preserve assistant message
        # ----------------------------------------------------

        messages.append(
            message
        )

        # ----------------------------------------------------
        # Execute tools
        # ----------------------------------------------------

        for (
            call_id,
            tool_name,
            arguments
        ) in tool_calls[
            :MAX_TOOL_CALLS_PER_TURN
        ]:

            result = execute_tool(
                call_id,
                tool_name,
                arguments
            )

            messages.append(
                {
                    "role": "tool",

                    "tool_call_id":
                        call_id,

                    "name":
                        tool_name,

                    "content":
                        json.dumps(
                            result,
                            ensure_ascii=False
                        ),
                }
            )

    return (
        "توقّف ALIX بعد الوصول إلى "
        "الحد الأقصى لعدد خطوات المهمة."
    )


# ============================================================
# HEALTH CHECK
# ============================================================

def check_server():

    health_url = (
        API_URL.split(
            "/v1/chat/completions"
        )[0]
        + "/health"
    )

    try:

        with urllib.request.urlopen(
            health_url,
            timeout=5
        ) as response:

            if response.status == 200:

                return True

    except Exception:

        pass

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 64)

    print(
        "              ALIX LOCAL AGENT v2"
    )

    print(
        "          Qwen 3.5 4B + llama.cpp"
    )

    print("=" * 64)

    print(
        f"API       : {API_URL}"
    )

    print(
        f"MODEL     : {MODEL}"
    )

    print(
        f"WORKSPACE : {WORKSPACE}"
    )

    print(
        f"LOGS      : {LOG_DIR}"
    )

    print("-" * 64)

    if check_server():

        print(
            "✓ llama.cpp: ONLINE"
        )

    else:

        print(
            "✗ llama.cpp: OFFLINE"
        )

        print()
        print(
            "شغّل llama-server أولاً."
        )

    print()
    print(
        "اكتب exit للخروج."
    )

    print(
        "جميع ملفات ALIX ستكون داخل workspace."
    )

    print()

    while True:

        try:

            user_input = input(
                "أنت > "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt
        ):

            print()
            print(
                "خروج."
            )

            break

        if not user_input:

            continue

        if user_input.lower() in {
            "exit",
            "quit",
            "خروج"
        }:

            print(
                "ALIX > إلى اللقاء."
            )

            break

        try:

            answer = run_agent(
                user_input
            )

            print()
            print(
                f"ALIX > {answer}"
            )

            print()

        except Exception as e:

            print()
            print(
                f"✗ خطأ: {e}"
            )

            print()

            log_event(
                "agent_error",
                {
                    "error": str(e)
                }
            )


if __name__ == "__main__":

    main()
