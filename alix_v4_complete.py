import os
import ast
import sys
import py_compile
import subprocess
import argparse
import json
import requests

# ==========================================
# Layer 1: Target Resolution
# ==========================================
# System Prompt Rule Injection
SYS_RULES = """
[CRITICAL CODING RULES - PYTHON 3.14+]
1. ALWAYS use ast.Constant for all literal values (numbers, strings, booleans, None). NEVER use deprecated AST nodes like ast.Num, ast.Str, ast.Bytes, or ast.NameConstant.
2. Ensure DoS protections (length checks, AST depth limits, node counts) are strictly maintained.
3. Standardize custom security errors under SafeEvalError.
"""

def resolve_target(target_name):
    if os.path.exists(target_name):
        return {"success": True, "path": target_name}
    return {"success": False, "error": f"Target '{target_name}' not found."}

# ==========================================
# Layer 5: Evidence Engine (Read-Only)
# ==========================================
def collect_evidence(file_path):
    if not os.path.exists(file_path):
        return {"success": False, "error": "File does not exist"}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return {
            "success": True,
            "file_path": file_path,
            "lines": lines,
            "total_lines": len(lines)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==========================================
# Layer 6: AST Diagnosis Engine
# ==========================================
class CodeStructureVisitor(ast.NodeVisitor):
    def __init__(self):
        self.issues = []

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.issues.append({
                "type": "runtime_error",
                "line": node.lineno,
                "statement": f"Bare 'except:' handler detected at line {node.lineno}"
            })
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self.issues.append({
                "type": "security_risk",
                "line": node.lineno,
                "statement": f"Dynamic execution via '{node.func.id}' at line {node.lineno}"
            })
        self.generic_visit(node)

def diagnose_evidence(evidence_data):
    if not evidence_data.get("success"):
        return {"success": False, "error": evidence_data.get("error")}

    file_path = evidence_data.get("file_path")
    lines = evidence_data.get("lines", [])
    hypotheses = []

    try:
        source_code = "".join(lines)
        parsed_ast = ast.parse(source_code, filename=file_path)
    except SyntaxError as syn_err:
        return {
            "success": True,
            "hypotheses": [{
                "type": "syntax",
                "line": syn_err.lineno or 0,
                "statement": f"SyntaxError: {syn_err.msg} at line {syn_err.lineno}, col {syn_err.offset}"
            }]
        }
    except Exception as e:
        return {"success": False, "error": f"AST Parsing failed: {str(e)}"}

    visitor = CodeStructureVisitor()
    visitor.visit(parsed_ast)
    hypotheses.extend(visitor.issues)

    for idx, line in enumerate(lines, 1):
        clean_line = line.strip()
        if clean_line.startswith("#") and ("TODO" in clean_line or "FIXME" in clean_line):
            hypotheses.append({
                "type": "incomplete_work",
                "line": idx,
                "statement": f"Incomplete work tag at line {idx}: {clean_line}"
            })

    return {"success": True, "hypotheses": hypotheses}

# ==========================================
# Layer 6.1 & 6.2: Verification Engine
# ==========================================
def build_verification_bridge(diagnosis_result):
    if not isinstance(diagnosis_result, dict) or not diagnosis_result.get("success"):
        return {"success": False, "verification_items": []}

    hypotheses = diagnosis_result.get("hypotheses", [])
    verification_items = []

    for index, hyp in enumerate(hypotheses, 1):
        if not isinstance(hyp, dict):
            continue

        hyp_type = str(hyp.get("type", "unknown")).lower()
        statement = hyp.get("statement", "")
        item_id = f"HYP-{index:03d}"

        if hyp_type == "syntax":
            required_evidence = "Syntax validation output via py_compile or explicit traceback."
            verification_method = "Run isolated syntax check (py_compile) on target file."
        elif hyp_type == "runtime_error":
            required_evidence = "Explicit runtime stack trace or failing unit test assertion."
            verification_method = "Execute target unit test or reproduce runtime execution flow."
        else:
            required_evidence = "Independent runtime proof or deterministic log."
            verification_method = "Perform targeted function execution under monitoring."

        verification_items.append({
            "id": item_id,
            "hypothesis": statement,
            "required_evidence": required_evidence,
            "verification_method": verification_method,
            "status": "unverified",
            "confirmed_bug": False
        })

    return {"success": True, "verification_items": verification_items}

def execute_verification(verification_bridge_result, target_file):
    if not verification_bridge_result.get("success"):
        return {"success": False, "error": "Invalid bridge input"}

    items = verification_bridge_result.get("verification_items", [])
    verified_results = []

    for item in items:
        item_id = item["id"]
        method = item["verification_method"]
        status = "unverified"
        confirmed = False
        execution_output = ""

        if "py_compile" in method:
            try:
                py_compile.compile(target_file, doraise=True)
                status = "false_positive"
                confirmed = False
                execution_output = "py_compile validation succeeded."
            except py_compile.PyCompileError as exc:
                status = "verified_bug"
                confirmed = True
                execution_output = f"py_compile failed: {str(exc)}"
            except Exception as e:
                execution_output = f"Execution error: {str(e)}"
        else:
            try:
                res = subprocess.run(
                    [sys.executable, "-m", "py_compile", target_file],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if res.returncode != 0:
                    status = "verified_bug"
                    confirmed = True
                    execution_output = res.stderr.strip()
                else:
                    status = "pending_runtime_test"
                    confirmed = False
                    execution_output = "Static verification clean; requires dynamic runtime test."
            except Exception as e:
                execution_output = f"Subprocess isolation error: {str(e)}"

        verified_results.append({
            "id": item_id,
            "hypothesis": item["hypothesis"],
            "status": status,
            "confirmed_bug": confirmed,
            "execution_evidence": execution_output
        })

    return {
        "success": True,
        "verified_items": verified_results,
        "total_confirmed_bugs": sum(1 for x in verified_results if x["confirmed_bug"])
    }

# ==========================================
# Layer 7: Auto-Remediation & Patch Engine
# ==========================================
def extract_clean_python_code(llm_response):
    if "```python" in llm_response:
        return llm_response.split("```python")[1].split("```")[0].strip()
    elif "```" in llm_response:
        return llm_response.split("```")[1].split("```")[0].strip()
    return llm_response.strip()

def apply_auto_patch(target_file, fixed_code):
    backup_file = f"{target_file}.bak"
    try:
        with open(target_file, "r", encoding="utf-8") as src:
            original_content = src.read()

        with open(backup_file, "w", encoding="utf-8") as bak:
            bak.write(original_content)

        with open(target_file, "w", encoding="utf-8") as dst:
            dst.write(fixed_code)

        py_compile.compile(target_file, doraise=True)
        return {"success": True, "backup": backup_file}

    except Exception as e:
        if os.path.exists(backup_file):
            with open(backup_file, "r", encoding="utf-8") as bak:
                with open(target_file, "w", encoding="utf-8") as dst:
                    dst.write(bak.read())
        return {"success": False, "error": str(e)}

# ==========================================
# Layer 8: Dynamic Unit Test Synthesizer Engine
# ==========================================
def run_dynamic_pytest_suite(target_file, provider="groq", model="openai/gpt-oss-120b"):
    module_name = os.path.splitext(os.path.basename(target_file))[0]
    test_file_path = f"test_generated_{module_name}.py"

    with open(target_file, "r", encoding="utf-8") as f:
        source_code = f.read()

    system_prompt = f"""
================ ALIX V4 DYNAMIC TEST SYNTHESIZER ================
TARGET FILE: {target_file} (Import as `{module_name}`)

SOURCE CODE:
{source_code}

INSTRUCTIONS:
1. Generate complete executable unit test code strictly using Python's standard `unittest` module.
2. Keep assertions concise and targeted to fit execution limits.
3. Create a test class inheriting from `unittest.TestCase` (e.g., `class Test{module_name.title()}(unittest.TestCase):`).
4. ALL test method names MUST start with the prefix `test_`. Ensure EVERY test method has valid indented statements inside its body.
5. End explicitly with `if __name__ == '__main__': unittest.main()`.
6. Do NOT import `pytest` or third-party libraries.
7. Return ONLY executable Python code inside ```python ... ``` blocks.
===================================================================
"""

    print(f"[*] Synthesizing Unit Test Suite via [{provider.upper()}]...")
    llm_reply = query_llm_agent(system_prompt, "Generate concise unittest.TestCase suite.", provider=provider, model=model, max_tokens=3000)
    test_code = extract_clean_python_code(llm_reply)

    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write(test_code)

    try:
        py_compile.compile(test_file_path, doraise=True)
    except py_compile.PyCompileError as syn_err:
        print(f"[!] Generated Test Suite Syntax Verification Failed: {syn_err}")
        return {"success": False, "error": "Synthesized code contains syntax errors"}

    print(f"[+] Generated Test Suite (Verified): {test_file_path}")
    print(f"[*] Executing Test Runner...")

    try:
        cmd = [sys.executable, test_file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        print("\n=== RUNTIME TEST EXECUTION OUTPUT ===")
        print(result.stdout if result.stdout else result.stderr)
        
        return {
            "success": result.returncode == 0,
            "test_file": test_file_path,
            "return_code": result.returncode
        }
    except Exception as e:
        print(f"[!] Execution Error: {str(e)}")
        return {"success": False, "error": str(e)}

# ==========================================
# Unified LLM Provider Interface
# ==========================================
def build_agent_verification_context(exec_result, target_file, fix_mode=False):
    verified_items = exec_result.get("verified_items", [])
    confirmed_bugs = [x for x in verified_items if x["confirmed_bug"]]
    pending_items = [x for x in verified_items if not x["confirmed_bug"]]

    with open(target_file, "r", encoding="utf-8") as f:
        source_code = f.read()

    context_prompt = f"""
================ ALIX V4 SYSTEM CONTEXT (ZERO-TRUST RULE) ================
TARGET FILE: {target_file}
TOTAL CONFIRMED BUGS: {len(confirmed_bugs)}

[ORIGINAL CODE]
{source_code}

[CONFIRMED BUGS (RUNTIME VERIFIED)]
"""
    if confirmed_bugs:
        for item in confirmed_bugs:
            context_prompt += f"- [{item['id']}] {item['hypothesis']}\n  Evidence: {item['execution_evidence']}\n"
    else:
        context_prompt += "None. No syntax execution errors verified.\n"

    context_prompt += "\n[UNVERIFIED RISKS & HYPOTHESES]\n"
    for item in pending_items:
        context_prompt += f"- [{item['id']}] Status: {item['status']} | Note: {item['hypothesis']}\n"

    if fix_mode:
        context_prompt += """
[STRICT AUTO-PATCHING INSTRUCTIONS]
1. Rewrite the complete source code to fix all confirmed bugs and replace unverified security risks and use ast.Constant for literals with clean, secure Python practices.
2. Return ONLY the complete executable Python code wrapped in ```python ... ``` blocks.
===========================================================================
"""
    else:
        context_prompt += """
[STRICT AGENT INSTRUCTIONS]
1. Do NOT claim syntax errors unless listed under CONFIRMED BUGS.
2. Provide code recommendations and risks clearly.
===========================================================================
"""
    return context_prompt

def query_llm_agent(system_context, user_prompt, provider="groq", model="openai/gpt-oss-120b", max_tokens=2500):
    provider = provider.lower()
    
    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return "[!] Error: GROQ_API_KEY is missing from environment."
        url = "https://api.groq.com/openai/v1/chat/completions"
        model_name = model or "openai/gpt-oss-120b"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
    elif provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return "[!] Error: DEEPSEEK_API_KEY is missing from environment."
        url = "https://api.deepseek.com/chat/completions"
        model_name = model or "deepseek-reasoner"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return "[!] Error: OPENROUTER_API_KEY is missing from environment."
        url = "https://openrouter.ai/api/v1/chat/completions"
        model_name = model or "openrouter/auto"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ALIX-Agent",
            "X-Title": "ALIX V4 Agent"
        }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"]
        else:
            return f"[!] Provider API Error ({provider.upper()}) {res.status_code}: {res.text}"
    except Exception as e:
        return f"[!] Request Exception: {str(e)}"

# ==========================================
# Main CLI Pipeline Engine
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="ALIX V4 Multi-Provider Autonomous Code Verification Engine")
    parser.add_argument("target", help="Target Python file to analyze")
    parser.add_argument("--ask", type=str, help="Send user prompt with zero-trust context")
    parser.add_argument("--fix", action="store_true", help="Auto-remediate code issues and create backup (.bak)")
    parser.add_argument("--test", action="store_true", help="Synthesize and run dynamic unit tests (Layer 8)")
    parser.add_argument("--provider", type=str, default="groq", choices=["groq", "deepseek", "openrouter"], help="API Provider (default: groq)")
    parser.add_argument("--model", type=str, default="openai/gpt-oss-120b", help="Specific model name")
    parser.add_argument("--tokens", type=int, default=2500, help="Max output tokens")
    parser.add_argument("--json", action="store_true", help="Output execution results in raw JSON format")
    args = parser.parse_args()

    target_res = resolve_target(args.target)
    if not target_res["success"]:
        print(f"[!] Resolution Error: {target_res['error']}")
        sys.exit(1)

    evidence = collect_evidence(target_res["path"])
    diagnosis = diagnose_evidence(evidence)
    bridge_result = build_verification_bridge(diagnosis)
    exec_result = execute_verification(bridge_result, target_res["path"])

    if args.json:
        print(json.dumps(exec_result, indent=2, ensure_ascii=False))
        return

    print(f"[*] ALIX V4 Engine Analyzed Target: {args.target}")
    print(f"[+] Total Lines Collected: {evidence.get('total_lines', 0)}")
    print(f"[+] Formulated Hypotheses: {len(diagnosis.get('hypotheses', []))}")
    print(f"[*] Confirmed Executable Bugs: {exec_result.get('total_confirmed_bugs', 0)}")

    if args.test:
        run_dynamic_pytest_suite(target_res["path"], provider=args.provider, model=args.model)
        return

    if args.fix:
        print(f"\n[*] Launching Layer 7 Auto-Remediation Engine via [{args.provider.upper()}]...")
        prompt = "Re-write the whole code safely addressing all identified security risks and bare excepts."
        agent_context = build_agent_verification_context(exec_result, target_res["path"], fix_mode=True)
        llm_reply = query_llm_agent(agent_context, prompt, provider=args.provider, model=args.model, max_tokens=args.tokens)
        
        fixed_code = extract_clean_python_code(llm_reply)
        patch_res = apply_auto_patch(target_res["path"], fixed_code)

        if patch_res["success"]:
            print(f"[+] Auto-Patch Applied Successfully!")
            print(f"[+] Backup Saved at: {patch_res['backup']}")
            print(f"[*] Re-verifying patched target with Syntax Engine...")
            re_check = py_compile.compile(target_res["path"], doraise=False)
            print("[✓] Post-Patch Syntax Check Passed Zero Errors.")
        else:
            print(f"[!] Auto-Patch Failed: {patch_res['error']}")
            print("[!] Original code restored from backup.")
        return

    if args.ask:
        print(f"\n[*] Querying Provider: [{args.provider.upper()}] | Model: [{args.model}]...")
        agent_context = build_agent_verification_context(exec_result, target_res["path"], fix_mode=False)
        llm_reply = query_llm_agent(agent_context, args.ask, provider=args.provider, model=args.model, max_tokens=args.tokens)
        print(f"\n=== {args.provider.upper()} LLM Response ===")
        print(llm_reply)

if __name__ == "__main__":
    main()
