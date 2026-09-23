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
    memory: Any | None = None,
) -> Dict[str, Callable[..., dict]]:
    from features.command_execution.composition import (
        build_run_command_controller,
        build_run_python_controller,
    )
    from features.system.composition import (
        build_git_status_controller,
        build_system_info_controller,
    )
    from features.file_access.composition import (
        build_create_directory_controller,
        build_delete_file_controller,
        build_list_files_controller,
        build_read_file_controller,
        build_search_files_controller,
        build_verify_file_controller,
        build_write_file_controller,
    )
    from features.web.composition import (
        build_web_fetch_controller,
        build_web_search_controller,
    )
    from features.memory.composition import (
        build_remember_fact_controller,
    )

    read_file_controller = build_read_file_controller(policy)
    write_file_controller = build_write_file_controller(policy)
    create_directory_controller = build_create_directory_controller(policy)
    run_command_controller = build_run_command_controller(policy)
    run_python_controller = build_run_python_controller(policy)
    system_info_controller = build_system_info_controller(policy)
    git_status_controller = build_git_status_controller(policy)

    delete_file_controller = build_delete_file_controller(policy)
    list_files_controller = build_list_files_controller(policy)
    search_files_controller = build_search_files_controller(policy)
    web_search_controller = build_web_search_controller()
    web_fetch_controller = build_web_fetch_controller()
    verify_file_controller = build_verify_file_controller(policy)
    remember_fact_controller = build_remember_fact_controller(memory)

    return {
        "create_directory": lambda **kwargs: create_directory_controller.handle(kwargs),
        "delete_file": lambda **kwargs: delete_file_controller.handle(kwargs),
        "list_files": lambda **kwargs: list_files_controller.handle(kwargs),
        "read_file": lambda **kwargs: read_file_controller.handle(kwargs),
        "search_files": lambda **kwargs: search_files_controller.handle(kwargs),
        "web_fetch": lambda **kwargs: web_fetch_controller.handle(kwargs),
        "web_search": lambda **kwargs: web_search_controller.handle(kwargs),
        "verify_file": lambda **kwargs: verify_file_controller.handle(kwargs),
        "remember_fact": lambda **kwargs: remember_fact_controller.handle(kwargs),
        "run_command": lambda **kwargs: run_command_controller.handle(kwargs),
        "run_python": lambda **kwargs: run_python_controller.handle(kwargs),
        "git_status": lambda **kwargs: git_status_controller.handle(kwargs),
        "system_info": lambda **kwargs: system_info_controller.handle(kwargs),
        "write_file": lambda **kwargs: write_file_controller.handle(kwargs),
    }
