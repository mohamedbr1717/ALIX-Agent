import ast

class ASTSecurityEnforcer(ast.NodeVisitor):
    BANNED_NODES = {ast.Import, ast.ImportFrom}
    BANNED_NAMES = {"eval", "exec", "compile", "open", "__import__", "getattr", "setattr"}

    def __init__(self):
        self.violations = []

    def visit_Import(self, node):
        self.violations.append("Unauthorized module import detected.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self.violations.append("Unauthorized module import detected.")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in self.BANNED_NAMES:
            self.violations.append(f"Forbidden system call access: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr.startswith("__"):
            self.violations.append(f"Reflection/Introspection attempt detected: {node.attr}")
        self.generic_visit(node)

def test_payload(name, payload):
    try:
        parsed = ast.parse(payload)
        enforcer = ASTSecurityEnforcer()
        enforcer.visit(parsed)
        if enforcer.violations:
            print(f"[BLOCKED - SUCCESS] {name}: {enforcer.violations[0]}")
            return True
        else:
            print(f"[FAIL - ESCAPED] {name}: Code passed AST verification!")
            return False
    except Exception as e:
        print(f"[BLOCKED - SYNTAX] {name}: Invalid AST structure ({e})")
        return True

def run_redteam_suite():
    print("=" * 55)
    print("      ALIX V4 ADVERSARIAL RED-TEAMING SUITE     ")
    print("=" * 55)
    
    payloads = {
        "Vector 1: OS Command Injection": "import os; os.system('ls')",
        "Vector 2: Reflection Bypass": "()." + "__class__" + "." + "__bases__[0]",
        "Vector 3: Dynamic Exec Injection": "eval('open(\"/etc/passwd\")')",
        "Vector 4: Builtin Poisoning": "__import__('sys').exit()",
        "Vector 5: Indirect Subclass Attack": "[c for c in ()." + "__class__." + "__mro__]",
    }
    
    passed = 0
    for name, code in payloads.items():
        if test_payload(name, code):
            passed += 1
            
    print("=" * 55)
    print(f"Red-Team Defense Score: {passed}/{len(payloads)} Attacks Mitigated ({passed/len(payloads)*100:.1f}%)")
    print("=" * 55)

if __name__ == "__main__":
    run_redteam_suite()
