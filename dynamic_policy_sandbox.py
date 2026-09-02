import ast
import json
import os

class DynamicASTEnforcer(ast.NodeVisitor):
    def __init__(self, policy_path="policy.json"):
        self.violations = []
        self.policy = self._load_policy(policy_path)
        
        self.banned_nodes = set(self.policy.get("banned_nodes", []))
        self.banned_names = set(self.policy.get("banned_names", []))
        self.banned_attributes = set(self.policy.get("banned_attributes", []))

    def _load_policy(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Policy configuration file not found at: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def visit_Import(self, node):
        if "Import" in self.banned_nodes:
            self.violations.append("Policy Violation: Dynamic module import prohibited.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if "ImportFrom" in self.banned_nodes:
            self.violations.append("Policy Violation: Dynamic module import from package prohibited.")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in self.banned_names:
            self.violations.append(f"Policy Violation: Access to forbidden system call '{node.id}'.")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in self.banned_attributes or node.attr.startswith("__"):
            self.violations.append(f"Policy Violation: Prohibited introspection/attribute access '{node.attr}'.")
        self.generic_visit(node)

def run_dynamic_policy_verification():
    print("=" * 55)
    print("      ALIX v4.1 DYNAMIC POLICY ENGINE VERIFICATION      ")
    print("=" * 55)
    
    enforcer = DynamicASTEnforcer("policy.json")
    print(f"Policy Loaded : {enforcer.policy.get('policy_name')} (v{enforcer.policy.get('version')})")
    
    test_code = "x = [c for c in ().__class__.__mro__]"
    parsed = ast.parse(test_code)
    enforcer.visit(parsed)
    
    if enforcer.violations:
        print(f"[STATUS] Violation Blocked Successfully: {enforcer.violations[0]}")
    else:
        print("[STATUS] Code Passed Verification.")
    print("=" * 55)

if __name__ == "__main__":
    run_dynamic_policy_verification()
