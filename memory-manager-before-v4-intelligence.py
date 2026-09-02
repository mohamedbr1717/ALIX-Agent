#!/usr/bin/env python3

import json
import re
import shutil
from datetime import datetime
from pathlib import Path


# ============================================================
# ALIX MEMORY MANAGER V4
# Standalone Safe Memory System
# ============================================================

BASE_DIR = Path.home() / "ALIX-Agent"

MEMORY_DIR = BASE_DIR / "memory"
BACKUP_DIR = MEMORY_DIR / "memory-backups"

TEST_MEMORY_FILE = MEMORY_DIR / "memory-v4-test.json"

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


MAX_HISTORY = 50
MAX_FACTS = 100
MAX_PREFERENCES = 100


# ============================================================
# DEFAULT STRUCTURE
# ============================================================

def default_memory():
    return {
        "facts": [],
        "preferences": [],
        "history": []
    }


# ============================================================
# SECURITY
# ============================================================

SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",
    r"sk-or-[A-Za-z0-9_-]{10,}",
    r"gsk_[A-Za-z0-9_-]{10,}",
    r"AIza[A-Za-z0-9_-]{20,}",
    r"api[_-]?key\s*[:=]\s*\S+",
    r"password\s*[:=]\s*\S+",
    r"passwd\s*[:=]\s*\S+",
    r"secret\s*[:=]\s*\S+",
    r"token\s*[:=]\s*\S+",
    r"authorization\s*[:=]\s*\S+",
]


def contains_secret(value):
    if not isinstance(value, str):
        return False

    for pattern in SECRET_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return True

    return False


def sanitize(value):
    """
    يمنع تخزين الأسرار داخل الذاكرة.
    """

    if isinstance(value, str):
        if contains_secret(value):
            return "[REDACTED]"

    return value


# ============================================================
# LOAD
# ============================================================

def load_memory(path=TEST_MEMORY_FILE):

    if not path.exists():
        return default_memory()

    try:

        data = json.loads(
            path.read_text(encoding="utf-8")
        )

    except (json.JSONDecodeError, OSError):

        print("⚠️ تعذر قراءة ملف الذاكرة، سيتم استخدام ذاكرة فارغة.")
        return default_memory()

    if not isinstance(data, dict):
        return default_memory()

    data.setdefault("facts", [])
    data.setdefault("preferences", [])
    data.setdefault("history", [])

    if not isinstance(data["facts"], list):
        data["facts"] = []

    if not isinstance(data["preferences"], list):
        data["preferences"] = []

    if not isinstance(data["history"], list):
        data["history"] = []

    return data


# ============================================================
# BACKUP
# ============================================================

def backup_memory(path=TEST_MEMORY_FILE):

    if not path.exists():
        return None

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    backup_path = (
        BACKUP_DIR /
        f"memory-v4-test-{timestamp}.json"
    )

    shutil.copy2(path, backup_path)

    return backup_path


# ============================================================
# SAVE
# ============================================================

def save_memory(memory, path=TEST_MEMORY_FILE):

    if not isinstance(memory, dict):
        raise TypeError("Memory must be a dictionary.")

    memory.setdefault("facts", [])
    memory.setdefault("preferences", [])
    memory.setdefault("history", [])

    memory["facts"] = memory["facts"][-MAX_FACTS:]
    memory["preferences"] = memory["preferences"][-MAX_PREFERENCES:]
    memory["history"] = memory["history"][-MAX_HISTORY:]

    backup_memory(path)

    temporary = path.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            memory,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temporary.replace(path)


# ============================================================
# FACTS
# ============================================================

def add_fact(key, value, path=TEST_MEMORY_FILE):

    key = sanitize(key)
    value = sanitize(value)

    if value == "[REDACTED]":
        print("🛡️ تم منع حفظ معلومة حساسة.")
        return False

    memory = load_memory(path)

    for fact in memory["facts"]:

        if isinstance(fact, dict) and fact.get("key") == key:

            fact["value"] = value
            save_memory(memory, path)

            print(f"🔄 تم تحديث الحقيقة: {key}")
            return True

    memory["facts"].append({
        "key": key,
        "value": value
    })

    save_memory(memory, path)

    print(f"🧠 تم حفظ الحقيقة: {key}")
    return True


def get_fact(key, path=TEST_MEMORY_FILE):

    memory = load_memory(path)

    for fact in memory["facts"]:

        if isinstance(fact, dict):
            if fact.get("key") == key:
                return fact.get("value")

    return None


# ============================================================
# PREFERENCES
# ============================================================

def add_preference(key, value, path=TEST_MEMORY_FILE):

    key = sanitize(key)
    value = sanitize(value)

    if value == "[REDACTED]":
        print("🛡️ تم منع حفظ معلومة حساسة.")
        return False

    memory = load_memory(path)

    for preference in memory["preferences"]:

        if (
            isinstance(preference, dict)
            and preference.get("key") == key
        ):

            preference["value"] = value

            save_memory(memory, path)

            print(f"🔄 تم تحديث التفضيل: {key}")
            return True

    memory["preferences"].append({
        "key": key,
        "value": value
    })

    save_memory(memory, path)

    print(f"❤️ تم حفظ التفضيل: {key}")
    return True


def get_preference(key, path=TEST_MEMORY_FILE):

    memory = load_memory(path)

    for preference in memory["preferences"]:

        if isinstance(preference, dict):
            if preference.get("key") == key:
                return preference.get("value")

    return None


# ============================================================
# HISTORY
# ============================================================

def add_history(user, assistant, path=TEST_MEMORY_FILE):

    if contains_secret(user) or contains_secret(assistant):

        print("🛡️ تم منع تسجيل رسالة تحتوي على سر محتمل.")
        return False

    memory = load_memory(path)

    memory["history"].append({
        "user": user,
        "assistant": assistant
    })

    save_memory(memory, path)

    return True


# ============================================================
# MEMORY SUMMARY
# ============================================================

def get_summary(path=TEST_MEMORY_FILE):

    memory = load_memory(path)

    return {
        "facts": len(memory["facts"]),
        "preferences": len(memory["preferences"]),
        "history": len(memory["history"])
    }


# ============================================================
# TEST SUITE
# ============================================================

def run_tests():

    print()
    print("=" * 60)
    print(" ALIX MEMORY MANAGER V4 TEST")
    print("=" * 60)
    print()

    # Start with clean test memory
    if TEST_MEMORY_FILE.exists():
        TEST_MEMORY_FILE.unlink()

    print("1️⃣ اختبار إنشاء الذاكرة")

    memory = load_memory()

    assert memory["facts"] == []
    assert memory["preferences"] == []
    assert memory["history"] == []

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("2️⃣ اختبار حفظ Fact")

    add_fact(
        "agent_name",
        "ALIX"
    )

    assert get_fact("agent_name") == "ALIX"

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("3️⃣ اختبار تحديث Fact")

    add_fact(
        "agent_name",
        "ALIX V4"
    )

    assert get_fact("agent_name") == "ALIX V4"

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("4️⃣ اختبار Preferences")

    add_preference(
        "language",
        "Arabic"
    )

    assert get_preference("language") == "Arabic"

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("5️⃣ اختبار History")

    add_history(
        "مرحبا ALIX",
        "مرحبا! كيف أساعدك؟"
    )

    memory = load_memory()

    assert len(memory["history"]) == 1

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("6️⃣ اختبار منع API Key")

    result = add_fact(
        "api_key",
        "sk-or-v1-THIS-IS-A-FAKE-KEY"
    )

    assert result is False

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("7️⃣ اختبار النسخ الاحتياطي")

    add_fact(
        "environment",
        "Termux Android"
    )

    backups = list(
        BACKUP_DIR.glob("memory-v4-test-*.json")
    )

    assert len(backups) >= 1

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("8️⃣ اختبار JSON")

    data = json.loads(
        TEST_MEMORY_FILE.read_text(
            encoding="utf-8"
        )
    )

    assert isinstance(data, dict)
    assert "facts" in data
    assert "preferences" in data
    assert "history" in data

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("9️⃣ اختبار الملخص")

    summary = get_summary()

    print(f"   Facts:        {summary['facts']}")
    print(f"   Preferences:  {summary['preferences']}")
    print(f"   History:      {summary['history']}")

    print("   ✅ PASS")

    # --------------------------------------------------------

    print()
    print("=" * 60)
    print(" 🎉 جميع اختبارات Memory Manager V4 نجحت")
    print("=" * 60)
    print()

    print(f"ملف الاختبار:")
    print(TEST_MEMORY_FILE)

    print()
    print("ملاحظة:")
    print("هذا الاختبار لم يلمس memory.json الأصلي.")
    print()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_tests()
