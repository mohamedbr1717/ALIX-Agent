"""
core/feature_bridge.py

النقطة الوحيدة المسموح لها في core/ بمعرفة features/ مباشرة.

core/agent.py و core/registry.py يستوردان معالجات الأدوات المُهاجَرة
من هنا فقط، لا من features.file_access.composition (أو أي composition
آخر لاحقًا) مباشرة. هذا يمنع تكرار منطق التركيب (composition) في أكثر
من مكان -- نفس فئة الخطأ التي أُصلحت مرارًا الليلة (list_files،
بوابة capability، ربط ToolRegistry) لكن على مستوى طبقة الربط نفسها.

لإضافة أداة مُهاجَرة جديدة (list_files، write_file، ...):
1. أضف سطرًا واحدًا هنا في build_migrated_tool_handlers().
2. core/agent.py و core/registry.py سيلتقطانها تلقائيًا، بلا أي
   تعديل إضافي فيهما.
"""

from __future__ import annotations

from typing import Any, Callable, Dict


def build_migrated_tool_handlers(
    policy: Any,
) -> Dict[str, Callable[..., dict]]:
    from features.command_execution.composition import (
        build_run_command_controller,
    )
    from features.file_access.composition import (
        build_delete_file_controller,
        build_read_file_controller,
        build_write_file_controller,
    )

    read_file_controller = build_read_file_controller(policy)
    write_file_controller = build_write_file_controller(policy)
    run_command_controller = build_run_command_controller(policy)

    delete_file_controller = build_delete_file_controller(policy)

    return {
        "delete_file": lambda **kwargs: delete_file_controller.handle(kwargs),
        "read_file": lambda **kwargs: read_file_controller.handle(kwargs),
        "run_command": lambda **kwargs: run_command_controller.handle(kwargs),
        "write_file": lambda **kwargs: write_file_controller.handle(kwargs),
    }
