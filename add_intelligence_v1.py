from pathlib import Path
import ast
import shutil
import re

AGENT = Path("agent.py")
BACKUP = Path("agent-before-intelligence-v1.py")

if not AGENT.exists():
    raise SystemExit("❌ agent.py غير موجود")

source = AGENT.read_text(encoding="utf-8")

# ------------------------------------------------------------
# 1. Safety checks
# ------------------------------------------------------------

tree = ast.parse(source)

functions = {
    node.name
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
}

required = {
    "run_agent",
    "create_plan",
    "detect_memory_intent",
    "auto_save_memory",
    "execute_tool",
}

missing = required - functions

if missing:
    raise SystemExit(
        "❌ المكونات المطلوبة غير موجودة: "
        + ", ".join(sorted(missing))
    )

if "INTELLIGENCE_LAYER_1" in source:
    raise SystemExit("⚠️ Intelligence Layer 1 موجودة بالفعل")

# ------------------------------------------------------------
# 2. Backup
# ------------------------------------------------------------

if not BACKUP.exists():
    shutil.copy2(AGENT, BACKUP)
    print("✓ BACKUP: OK")
else:
    print("✓ BACKUP already exists")

# ------------------------------------------------------------
# 3. Intelligence Layer 1
# ------------------------------------------------------------

marker = "\n# ============================================================\n# AGENT LOOP\n# ============================================================\n"

if marker not in source:
    raise SystemExit("❌ لم يتم العثور على بداية AGENT LOOP")

intelligence = r'''

# ============================================================
# INTELLIGENCE_LAYER_1
# ALIX V4 — Intent Intelligence
# ============================================================

def classify_intent(user_input):
    """
    تصنيف أولي لطلب المستخدم.

    لا يستخدم Terminal.
    لا يستخدم أدوات خارجية.
    لا ينفذ أي إجراء.

    Returns:
        chat
        memory
        file_read
        file_search
        file_write
        terminal
        investigation
        planning
    """

    if not isinstance(user_input, str):
        return "chat"

    text = user_input.strip().lower()

    if not text:
        return "chat"

    # -----------------------------
    # Memory
    # -----------------------------

    memory_words = [
        "ذاكرة",
        "تفضيل",
        "fact",
        "preference",
        "احفظ",
        "تذكر",
        "استرجع",
        "ما قيمة",
    ]

    if any(word in text for word in memory_words):
        return "memory"

    # -----------------------------
    # File reading
    # -----------------------------

    read_words = [
        "اقرأ الملف",
        "اعرض الملف",
        "اعرض أول",
        "اقرأ أول",
        "read file",
        "show file",
    ]

    if any(word in text for word in read_words):
        return "file_read"

    # -----------------------------
    # File search
    # -----------------------------

    search_words = [
        "ابحث عن ملفات",
        "ابحث في المشروع",
        "ابحث عن",
        "search files",
        "find files",
    ]

    if any(word in text for word in search_words):
        return "file_search"

    # -----------------------------
    # File modification
    # -----------------------------

    write_words = [
        "أنشئ ملف",
        "أنشئ سكريبت",
        "عدّل الملف",
        "عدل الملف",
        "اكتب في الملف",
        "غيّر الملف",
        "تعديل الكود",
        "write file",
        "edit file",
        "modify file",
    ]

    if any(word in text for word in write_words):
        return "file_write"

    # -----------------------------
    # Terminal
    # -----------------------------

    terminal_words = [
        "نفذ أمر",
        "شغل الأمر",
        "شغّل الأمر",
        "terminal",
        "ترمينال",
        "bash",
        "shell",
        "command",
    ]

    if any(word in text for word in terminal_words):
        return "terminal"

    # -----------------------------
    # Investigation / debugging
    # -----------------------------

    investigation_words = [
        "اكتشف الخطأ",
        "افحص المشروع",
        "حلل المشروع",
        "شخّص الخطأ",
        "لماذا لا يعمل",
        "ما سبب الخطأ",
        "debug",
        "diagnose",
        "inspect project",
    ]

    if any(word in text for word in investigation_words):
        return "investigation"

    # -----------------------------
    # Complex planning
    # -----------------------------

    planning_words = [
        "خطط",
        "خطة",
        "خطوة بخطوة",
        "نفذ المشروع",
        "ابن المشروع",
        "طوّر المشروع",
        "طور المشروع",
        "أضف نظام",
        "صمم نظام",
        "build",
        "develop",
        "implement",
        "architecture",
    ]

    if any(word in text for word in planning_words):
        return "planning"

    return "chat"


def intelligence_layer_1(user_input):
    """
    ALIX V4 Intelligence Layer 1.

    يحلل الطلب فقط ويحدد:
    - intent
    - هل يحتاج تخطيطًا
    - هل يحتاج أدوات

    لا ينفذ أدوات ولا Terminal.
    """

    intent = classify_intent(user_input)

    planning_intents = {
        "planning",
        "investigation",
    }

    tool_intents = {
        "memory",
        "file_read",
        "file_search",
        "file_write",
        "terminal",
        "investigation",
    }

    return {
        "intent": intent,
        "needs_plan": intent in planning_intents,
        "needs_tools": intent in tool_intents,
    }

'''

source = source.replace(marker, intelligence + marker, 1)

# ------------------------------------------------------------
# 4. Validate syntax
# ------------------------------------------------------------

try:
    ast.parse(source)
except SyntaxError as e:
    print("❌ AST VALIDATION FAILED")
    print(e)

    if BACKUP.exists():
        shutil.copy2(BACKUP, AGENT)

    raise SystemExit(1)

AGENT.write_text(source, encoding="utf-8")

print("✓ INTELLIGENCE LAYER 1 ADDED")
print("✓ classify_intent: OK")
print("✓ intelligence_layer_1: OK")
print("✓ MEMORY: UNTOUCHED")
print("✓ AGENTIC LOOP: UNTOUCHED")
print("✓ AST: OK")

# ------------------------------------------------------------
# 5. Final structural test
# ------------------------------------------------------------

final_source = AGENT.read_text(encoding="utf-8")
final_tree = ast.parse(final_source)

final_functions = {
    node.name
    for node in final_tree.body
    if isinstance(node, ast.FunctionDef)
}

required_after = required | {
    "classify_intent",
    "intelligence_layer_1",
}

missing_after = required_after - final_functions

if missing_after:
    print("❌ FINAL STRUCTURE FAILED")

    if BACKUP.exists():
        shutil.copy2(BACKUP, AGENT)
        print("✓ BACKUP RESTORED")

    raise SystemExit(1)

print("✓ STRUCTURE: OK")
print("✓ ALIX V4 INTELLIGENCE LAYER 1 READY")
