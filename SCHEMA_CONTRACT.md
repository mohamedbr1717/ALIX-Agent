# عقد النتيجة الموحد لكل أدوات ALIX-Agent

هذا هو الـ schema الفعلي الذي كل أداة (عبر SafeExecutor أو
ToolRegistry.execute()) تُعيده، نجاحًا كان أم فشلًا. مفروض آليًا
عبر ExecutionResult.to_dict() في core/executor.py.

## الشكل

الحقول: ok (bool), action (str), message (str), stdout (str),
stderr (str), returncode (int أو null), evidence (dict), duration (float).

لا مفاتيح أخرى مسموحة على المستوى الأعلى.

## من يفرض هذا العقد فعليًا؟

1. ExecutionResult.to_dict() في core/executor.py.
2. ToolRegistry._deny() في core/registry.py — كل مسار رفض مبكر.
3. FileSystemTools.list_files في tools/filesystem.py.

## قيد فعلي على read_file: حد أدنى 500 حرف لـ max_output

SafeExecutor.__init__ يفرض max_output = max(500, requested_value)
دائمًا. قيمة أقل من 500 تُرفَع صامتًا إلى 500. هذا قيد إنتاجي مقصود.
اكتُشف عند بناء WorkspaceFileStorageAdapter (features/file_access)
حين فوّض لـ SafeExecutor الحقيقي بدل نسخة مكرَّرة كانت تقبل أي قيمة
بلا حد أدنى.

## ما لم يُغطَّ بعد

الطبقات الجديدة تحت features/ (Vertical Slice architecture) يجب أن
تلتزم بنفس هذا العقد في كل مسارات النجاح والفشل، بما فيها التحقق
المبكر من المعطيات (انظر ملاحظة في ReadFileUseCase.execute()).
