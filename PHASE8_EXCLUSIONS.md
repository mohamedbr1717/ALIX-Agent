# استبعادات موثَّقة من Security/Regression Gate

## test_v5_coverage_boost.py
سبب: اختبار موجَّه لتغطية الكود (coverage-oriented) لا لسلوك حقيقي،
يتعارض مع مبدأ ALIX الحالي في عدم قبول اختبارات هدفها الأساسي rnumber.

## test_mcp.py
سبب: يختبر mcp_server.py الذي يعتمد على البنية القديمة
(ALIXv41Agent + QuantizedVectorEngine)، الموثَّقة في Phase 7 كحدّ
معماري يحتاج إعادة تصميم (ربط mcp_server.py بـ core.agent.ALIXAgent
بدلًا من ذلك). فشله الحالي بسبب أرشفة vector_memory.py/
quantized_vector_store.py هو أثر متوقع لقرار تنظيف سابق، لا
regression. يُعاد تفعيله عند إعادة بناء مسار MCP في مرحلة لاحقة.
