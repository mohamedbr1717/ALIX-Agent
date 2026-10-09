"""Policy _ConfigMixin (private)."""
from __future__ import annotations

from pathlib import Path
class _ConfigMixin:
    """Methods moved verbatim."""

    def __init__(self):
        # =========================================================
        # Workspace
        # =========================================================

        self.base_dir = (Path.home() / "ALIX-Agent").resolve()
        self.workspace = (self.base_dir / "workspace").resolve()

        self.workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        # =========================================================
        # Permission Levels
        # =========================================================

        self.permission_levels = {
            "read": 0,
            "write": 1,
            "execute": 2,
            "destructive": 3,
        }

        # =========================================================
        # Scheduled Mode
        # =========================================================
        # Set by the scheduler daemon on its own agent instance.
        # In scheduled mode there is no user to confirm with, so:
        #  - destructive tools are NEVER allowed (fail-closed),
        #  - other tools only up to the per-task pre-authorized
        #    ceiling in scheduled_allow (granted at schedule time),
        #  - the scheduler control-plane tools themselves are
        #    disabled (a scheduled task cannot schedule/cancel).
        self.scheduled_mode = False
        self.scheduled_allow = "read"

        # =========================================================
        # Capability Gates
        # =========================================================
        # High-risk capabilities are disabled by default.
        # A disabled capability must be rejected before execution.
        self.tool_argument_schema = {
            "list_files": {
                "allowed": {"path"},
                "required": {"path"},
            },
            "read_file": {
                "allowed": {"path", "start_line", "end_line"},
                "required": {"path"},
            },
            "write_file": {
                "allowed": {"path", "content"},
                "required": {"path", "content"},
            },
            "create_directory": {
                "allowed": {"path"},
                "required": {"path"},
            },
            "delete_file": {
                "allowed": {"path"},
                "required": {"path"},
            },
            "search_files": {
                "allowed": {"pattern", "path", "max_matches"},
                "required": {"pattern"},
            },
            "run_python": {
                "allowed": {"script_path"},
                "required": {"script_path"},
            },
            "run_command": {
                "allowed": {"command"},
                "required": {"command"},
            },
            "system_info": {
                "allowed": set(),
                "required": set(),
            },
            "git_status": {
                "allowed": {"action"},
                "required": set(),
            },
            "remember_fact": {
                "allowed": {"fact", "is_preference"},
                "required": {"fact"},
            },
            "verify_file": {
                "allowed": {"path"},
                "required": {"path"},
            },
            "web_search": {
                "allowed": {"query", "max_results"},
                "required": {"query"},
            },
            "web_fetch": {
                "allowed": {"url", "max_chars"},
                "required": {"url"},
            },
            "phone_call": {
                "allowed": {"number"},
                "required": {"number"},
            },
            "send_sms": {
                "allowed": {"number", "message"},
                "required": {"number", "message"},
            },
            "notify": {
                "allowed": {"title", "content"},
                "required": {"content"},
            },
            "resolve_contact": {
                "allowed": {"name"},
                "required": {"name"},
            },
            "repo_map": {
                "allowed": {"root", "max_depth", "max_entries"},
                "required": set(),
            },
            "search_code": {
                "allowed": {"query", "root", "max_results", "case_sensitive"},
                "required": {"query"},
            },
            "pack_context": {
                "allowed": {"root", "focus", "max_tokens", "max_files"},
                "required": set(),
            },
        }

        self.capabilities = {
            "run_python": False,
        }

        self.tool_permissions = {
            "list_files": "read",
            "read_file": "read",
            "search_files": "read",
            "system_info": "read",
            "git_status": "read",
            "verify_file": "read",

            "write_file": "write",
            "create_directory": "write",
            "remember_fact": "write",

            "run_python": "execute",
            "run_command": "execute",

            "delete_file": "destructive",

            "web_search": "read",
            "web_fetch": "read",
            "browse_page": "read",
            "browser_fill": "execute",
            "browser_submit": "destructive",
            "repo_map": "read",
            "search_code": "read",
            "pack_context": "read",

            "schedule_task": "write",
            "list_scheduled_tasks": "read",
            "cancel_scheduled_task": "write",
            "gmail_search": "read",
            "gmail_read": "read",
            "gmail_reply": "destructive",
            "gmail_send": "destructive",
            "phone_call": "destructive",
            "send_sms": "destructive",
            "notify": "read",
            "resolve_contact": "read",
        }

        # =========================================================
        # Command Allowlist
        # =========================================================

        self.allowed_commands = {
            # Navigation / inspection
            "pwd",
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "wc",
            "sort",
            "uniq",
            "cut",
            "tr",
            "echo",
            "printf",
            "date",
            "whoami",
            "uname",
            "df",
            "du",
            "free",
            "file",
            "which",

            # Python
            "python",
            "python3",

            # Git
            "git",
        }

        # =========================================================
        # Explicitly Blocked Commands
        # =========================================================

        self.blocked_commands = {
            "rm",
            "rmdir",
            "unlink",
            "mkfs",
            "mkfs.ext4",
            "dd",

            "chmod",
            "chown",
            "chgrp",
            "setfacl",

            "mount",
            "umount",

            "su",
            "sudo",
            "doas",

            "reboot",
            "shutdown",
            "poweroff",
            "halt",

            "kill",
            "pkill",
            "killall",

            "iptables",
            "ip6tables",
            "nft",

            "termux-chroot",
            "proot",
            "proot-distro",

            "passwd",
            "useradd",
            "userdel",
            "usermod",

            "crontab",

            "ssh",
            "scp",
            "sftp",

            "nc",
            "netcat",
            "ncat",

            "telnet",

            "curl",
            "wget",

            "busybox",

            "env",
            "printenv",

            "bash",
            "sh",
            "zsh",
            "fish",

            "docker",
            "podman",

            "mountpoint",
        }

        # =========================================================
        # Git Read-Only Allowlist
        # =========================================================

        self.allowed_git_commands = {
            "status",
            "log",
            "diff",
            "show",
            "branch",
            "rev-parse",
            "tag",
        }

        # Git options that can alter repository state or execute
        # external programs are forbidden.
        self.blocked_git_tokens = {
            "--exec",
            "--upload-pack",
            "--receive-pack",
            "--config",
            "-c",
            "--work-tree",
            "--git-dir",
            "--bare",
            "--template",
            "--paginate",
            "--no-pager",
        }

        # =========================================================
        # Sensitive Names
        # =========================================================

        self.sensitive_names = {
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            ".env.test",

            ".git-credentials",
            ".gitconfig",

            "credentials",
            "credentials.json",

            "id_rsa",
            "id_ed25519",
            "id_ecdsa",

            "authorized_keys",

            "passwords.txt",
            "password.txt",

            "secrets.txt",
            "secret.txt",
            "secret.json",
            "secrets.json",

            "tokens.json",
            "token.json",

            "apikey.txt",
            "api_keys.txt",

            ".npmrc",
            ".pypirc",
            ".netrc",
        }

        self.sensitive_directories = {
            ".ssh",
            ".gnupg",
            ".aws",
            ".config/gcloud",
        }

        self.sensitive_extensions = {
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".crt",
            ".cer",
            ".der",
        }

        # =========================================================
        # Dangerous Patterns
        # =========================================================

        self.blocked_patterns = [
            # Shell operators
            r";",
            r"&&",
            r"\|\|",
            r"\|",
            r"&",
            r"\r|\n",

            # Command substitution
            r"`",
            r"\$\(",
            r"\$\{",

            # Redirection
            r">\s*",
            r"<\s*",

            # Traversal
            r"(?:^|/)\.\.(?:/|$)",
            r"~\/\.\.",

            # Absolute system paths
            r"(?:^|/)(etc|proc|sys|dev|root|system|vendor)(?:/|$)",

            # Android internals
            r"/data/data",
            r"/data/user",
            r"/data/local",
            r"/system/",
            r"/vendor/",

            # Privilege escalation
            r"\bsudo\b",
            r"\bsu\b",
            r"\bdoas\b",

            # Service control
            r"\bsystemctl\b",
            r"\bservice\b",

            # Shell execution
            r"\bbash\s+-c\b",
            r"\bsh\s+-c\b",
            r"\bzsh\s+-c\b",

            # Inline code execution
            r"\bpython\s+-c\b",
            r"\bpython3\s+-c\b",

            # Network download + execution
            r"\bcurl\b.*\b(sh|bash|python|python3)\b",
            r"\bwget\b.*\b(sh|bash|python|python3)\b",

            # Execution helpers
            r"\bxargs\b",
            r"\beval\b",
            r"\bexec\b",

            # Background execution
            r"&\s*$",

            # Null byte
            r"\x00",
        ]

        # =========================================================
        # Resource Limits
        # =========================================================

        self.max_command_length = 1000
        self.max_path_length = 500
        self.max_search_pattern_length = 200
        self.max_search_matches = 20

        # Maximum number of arguments for a command.
        self.max_command_args = 32

        # Prevent absurdly long individual arguments.
        self.max_argument_length = 500


