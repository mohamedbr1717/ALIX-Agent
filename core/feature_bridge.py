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
        build_browse_page_controller,
        build_browser_fill_controller,
        build_browser_submit_controller,
        build_web_fetch_controller,
        build_web_search_controller,
    )
    from features.memory.composition import (
        build_remember_fact_controller,
    )
    from features.scheduler.composition import (
        build_cancel_task_controller,
        build_list_tasks_controller,
        build_schedule_task_controller,
    )
    from features.phone.composition import (
        build_notify_controller,
        build_phone_call_controller,
        build_send_sms_controller,
    )
    from features.contacts.composition import (
        build_resolve_contact_controller,
    )
    from features.calendar.composition import build_calendar_controllers
    from features.history.composition import build_history_controllers
    from features.repo_context.composition import (
        build_pack_context_controller,
        build_repo_map_controller,
        build_search_code_controller,
    )
    from features.gmail.composition import (
        build_gmail_read_controller,
        build_gmail_reply_controller,
        build_gmail_search_controller,
        build_gmail_send_controller,
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
    browse_page_controller = build_browse_page_controller()
    browser_fill_controller = build_browser_fill_controller()
    browser_submit_controller = build_browser_submit_controller()
    verify_file_controller = build_verify_file_controller(policy)
    remember_fact_controller = build_remember_fact_controller(memory)
    schedule_task_controller = build_schedule_task_controller(policy)
    list_tasks_controller = build_list_tasks_controller(policy)
    cancel_task_controller = build_cancel_task_controller(policy)
    phone_call_controller = build_phone_call_controller(policy)
    send_sms_controller = build_send_sms_controller(policy)
    notify_controller = build_notify_controller(policy)
    resolve_contact_controller = build_resolve_contact_controller(policy)
    calendar_controllers = build_calendar_controllers(policy)
    history_controllers = build_history_controllers(policy)
    repo_map_controller = build_repo_map_controller(policy)
    search_code_controller = build_search_code_controller(policy)
    pack_context_controller = build_pack_context_controller(policy)
    gmail_search_controller = build_gmail_search_controller()
    gmail_read_controller = build_gmail_read_controller()
    gmail_reply_controller = build_gmail_reply_controller()
    gmail_send_controller = build_gmail_send_controller()

    handlers = {
        "create_directory": lambda **kwargs: create_directory_controller.handle(kwargs),
        "delete_file": lambda **kwargs: delete_file_controller.handle(kwargs),
        "list_files": lambda **kwargs: list_files_controller.handle(kwargs),
        "read_file": lambda **kwargs: read_file_controller.handle(kwargs),
        "search_files": lambda **kwargs: search_files_controller.handle(kwargs),
        "web_fetch": lambda **kwargs: web_fetch_controller.handle(kwargs),
        "browse_page": lambda **kwargs: browse_page_controller.handle(kwargs),
        "browser_fill": lambda **kwargs: browser_fill_controller.handle(kwargs),
        "browser_submit": lambda **kwargs: browser_submit_controller.handle(kwargs),
        "web_search": lambda **kwargs: web_search_controller.handle(kwargs),
        "verify_file": lambda **kwargs: verify_file_controller.handle(kwargs),
        "remember_fact": lambda **kwargs: remember_fact_controller.handle(kwargs),
        "run_command": lambda **kwargs: run_command_controller.handle(kwargs),
        "run_python": lambda **kwargs: run_python_controller.handle(kwargs),
        "git_status": lambda **kwargs: git_status_controller.handle(kwargs),
        "system_info": lambda **kwargs: system_info_controller.handle(kwargs),
        "write_file": lambda **kwargs: write_file_controller.handle(kwargs),
        "repo_map": lambda **kwargs: repo_map_controller.handle(kwargs),
        "search_code": lambda **kwargs: search_code_controller.handle(kwargs),
        "pack_context": lambda **kwargs: pack_context_controller.handle(kwargs),
        "schedule_task": lambda **kwargs: schedule_task_controller.handle(kwargs),
        "list_scheduled_tasks": lambda **kwargs: list_tasks_controller.handle(kwargs),
        "cancel_scheduled_task": lambda **kwargs: cancel_task_controller.handle(kwargs),
        "gmail_search": lambda **kwargs: gmail_search_controller.handle(kwargs),
        "gmail_read": lambda **kwargs: gmail_read_controller.handle(kwargs),
        "gmail_reply": lambda **kwargs: gmail_reply_controller.handle(kwargs),
        "gmail_send": lambda **kwargs: gmail_send_controller.handle(kwargs),
        "phone_call": lambda **kwargs: phone_call_controller.handle(kwargs),
        "send_sms": lambda **kwargs: send_sms_controller.handle(kwargs),
        "notify": lambda **kwargs: notify_controller.handle(kwargs),
        "resolve_contact": lambda **kwargs: resolve_contact_controller.handle(kwargs),
        "calendar_list": lambda **kwargs: calendar_controllers["calendar_list"].handle(kwargs),
        "calendar_add": lambda **kwargs: calendar_controllers["calendar_add"].handle(kwargs),
        "calendar_delete": lambda **kwargs: calendar_controllers["calendar_delete"].handle(kwargs),
        "history": lambda **kwargs: history_controllers["history"].handle(kwargs),
        "undo": lambda **kwargs: history_controllers["undo"].handle(kwargs),
    }

    # History logging hook for the agent.
    handlers["_history_log"] = history_controllers["log_action"]
    # Inverse computation + store access (keeps core free of feature imports).
    from features.history.inverse import (
        compute_inverse as _compute_inverse,
        summarize_action as _summarize_action,
    )
    handlers["_history_inverse"] = _compute_inverse
    handlers["_history_summarize"] = _summarize_action
    handlers["_history_mark_undone"] = history_controllers[
        "log_action"
    ]._store.mark_undone

    return handlers


def build_task_store(path=None):
    """Task store shared by the scheduler tools and the daemon."""
    from features.scheduler.composition import (
        build_task_store as _build,
    )

    return _build(path)


def build_run_due_tasks_use_case(
    store,
    executor,
    clock=None,
    audit_fn=None,
):
    """Due-task runner for the scheduler daemon (via the bridge)."""
    from features.scheduler.application.use_cases.run_due_tasks import (
        RunDueTasksUseCase,
    )

    return RunDueTasksUseCase(
        store=store,
        executor=executor,
        clock=clock,
        audit_fn=audit_fn,
    )


def build_voice_transcribe_controller():
    """Voice transcription controller for telegram_bot.py (via the bridge)."""
    from features.voice.composition import (
        build_voice_transcribe_controller as _build,
    )

    return _build()


def build_gmail_search_controller():
    """Gmail search controller for telegram_bot.py (via the bridge)."""
    from features.gmail.composition import (
        build_gmail_search_controller as _build,
    )

    return _build()


def build_gmail_read_controller():
    """Gmail read controller for telegram_bot.py (via the bridge)."""
    from features.gmail.composition import (
        build_gmail_read_controller as _build,
    )

    return _build()


def build_gmail_reply_controller():
    """Gmail reply controller for telegram_bot.py (via the bridge)."""
    from features.gmail.composition import (
        build_gmail_reply_controller as _build,
    )

    return _build()


def build_gmail_send_controller():
    """Gmail send controller for telegram_bot.py (via the bridge)."""
    from features.gmail.composition import (
        build_gmail_send_controller as _build,
    )

    return _build()
