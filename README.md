# ALIX V5 Enterprise Architecture 🚀

**ALIX V5 Enterprise** (`v5.0.0`) هو نظام تشغيل وتأمين وكلاء الذكاء الاصطناعي (AI Agent OS) المصمم للتنفيذ المحلي الآمن، مع دعم كامل لبروتوكول MCP، واسترجاع دلالي موفر للموارد تحت الملي ثانية.

---

## 🏗️ المعمارية الهندسية (Core Architecture)

يتكون النظام من أربع طبقات رئيسية مصلدة:

1. **بروتوكول MCP الموحد (`mcp_server.py`)**:
   * تطبيق معيار **Model Context Protocol (JSON-RPC 2.0)** عبر القناة القياسية (`stdio`).
   * فصل تام للمجاري: تخصيص `stdout` للبيانات التزامنية الصافية، وتوجيه كافة السجلات والتشخيصات إلى `stderr` لمنع التلوث البنيوي.

2. **محرك العزل الهجين (AST Policy Enforcer + WASM Sandbox)**:
   * **AST Enforcer (`core/policy.py`)**: فحص شجرة النحو المجرد لتطبيقات الأكواد قبل التنفيذ بزمن استجابة < 0.35 ms.
   * **WASM Micro-Sandbox (`wasm_sandbox.py`)**: بيئة معزولة لعزل الحمولات البرمجية ومنع الوصول غير المصرح لنظام التشغيل.

3. **سجل التدقيق التشفيري (`merkle_logger.py`)**:
   * توثيق تعاقبي لكل عمليات التنفيذ في شجرة Merkle باستخدام دالة **SHA-256**.
   * كشف التزوير والتعديل الجنائي واكتشاف الانحرافات التشغيلية تلقائياً.

4. **الذاكرة المتجهية المكمّمة (`quantized_vector_store.py`)**:
   * محرك بحث دلالي موفر للموارد معتمد على تكميم المتجهات **INT8 Quantization**.
   * زمن استرجاع تحت الملي ثانية (≈ 0.22 ms) مع معامل تطابق يتجاوز 0.97.

---

## 📊 مؤشرات الأداء الميداني (Benchmarks)

| المكون / العملية | زمن الاستجابة (Latency) | معيار السلامة والامتثال |
|---|---|---|
| **MCP Handshake (`initialize`)** | < 0.45 ms | JSON-RPC 2.0 Compliant |
| **AST Policy Evaluation** | ≈ 0.34 ms | Strict_Hardened_AST_Policy |
| **INT8 Vector Search** | ≈ 0.22 ms | Cosine Similarity > 0.97 |
| **CI/CD Test Coverage** | - | > 80% (Pass) |

---

## ⚡ التشغيل والربط السريع

### 1. تشغيل خادم MCP
```bash
python mcp_server.py
```

### 2. تشغيل مجموعة الاختبارات الشاملة
```bash
python -m unittest test_v5_full_coverage.py
```

### 3. الربط مع Claude Desktop
أضف الإعدادات التالية في ملف `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "alix-agent": {
      "command": "python3",
      "args": [
        "/المسار/الكامل/إلى/ALIX-Agent/mcp_server.py"
      ]
    }
  }
}
```

---

## 🛡️ الترخيص والأمان
تخضع كافة الاستدعاءات عبر أداة `alix_execute_code` لفحص معيار سياسة الأمان الصارمة `Strict_Hardened_AST_Policy (v4.1.0)`.
