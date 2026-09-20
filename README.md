# ALIX-Agent 🤖

وكيل ذكاء اصطناعي شخصي يعمل على Termux (Android) — محرك تنفيذ هجين آمن،
بتوجيه مزدوج بين OpenRouter ونموذج محلي.

## البنية

```
main.py
└── core/agent.py              # ALIXAgent: حلقة الوكيل (تفكير → أدوات → تنفيذ)
    ├── core/registry.py       # ToolRegistry: تسجيل الأدوات والتوجيه
    ├── core/policy.py         # Policy: عزل مساحة العمل وحدود الموارد
    ├── core/executor.py       # SafeExecutor: تنفيذ آمن للأوامر
    ├── core/memory.py         # ذاكرة دائمة (memory/memory.json)
    ├── core/llm.py            # HybridLLM: OpenRouter أولًا، ثم المحلي احتياطيًا
    ├── core/sandbox.py        # صندوق عزل للتنفيذ
    ├── core/observability.py  # مراقبة وتشخيص
    └── core/feature_bridge.py # جسر الشرائح المهيكلة
└── features/file_access/      # شريحة رأسية: domain → application → infrastructure → interfaces
    ├── read_file / write_file  (dto, use_cases, ports, adapters, controllers)
    └── composition.py           # تجميع الشريحة
└── mcp_server.py              # خادم MCP (JSON-RPC 2.0) مبني على الكور
```

## الإعداد

```bash
pip install python-dotenv openai
pkg install proot -y
```

أنشئ ملف `.env` في جذر المشروع (مستثنى من git):

```
OPENROUTER_API_KEY=sk-or-v1-...
# اختياري:
OPENROUTER_MODEL=openai/gpt-oss-120b
ALIX_LOCAL_MODEL=Qwen3.5-4B-Instruct-Q4_K_M.gguf
```

### نموذج محلي (اختياري)

```bash
~/llama.cpp/build/bin/llama-server -m /path/to/model.gguf --port 8081 -c 4096 &
```

الوكيل يستخدم OpenRouter أولًا عند توفر مفتاح صالح،
ويتحول تلقائيًا إلى المحلي (`127.0.0.1:8081`) عند الفشل.

## التشغيل

```bash
python main.py
```

أوامر داخلية: `status` · `memory` · `clear-history` · `help` · `exit`

## الاختبارات

```bash
python -m pytest test_mcp.py test_architecture_boundaries.py \
  test_read_file_feature.py test_write_file_feature.py -q
python test_alix_real_evaluation_v2.py   # تقييم التنفيذ الحقيقي: 16 فحصًا
```

## الأمان

- حصر كل المسارات داخل `workspace/`
- رفض محاولات حقن الأوامر والقوائم السوداء
- fail-closed: الأدوات المعطلة لا تُحدث أي أثر جانبي
- نسخة احتياطية `.alix-backup` عند استبدال أي ملف
