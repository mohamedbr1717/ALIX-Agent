import json
import time
import os
import ast

class PolicyValidationError(Exception):
    pass

class LivePolicyEngine:
    REQUIRED_FIELDS = {"version", "policy_name", "banned_nodes", "banned_names", "banned_attributes"}

    def __init__(self, policy_path="policy.json"):
        self.policy_path = policy_path
        self.last_mtime = 0
        self.policy_data = {}
        self.reload_policy()

    def validate_schema(self, data):
        missing = self.REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise PolicyValidationError(f"Invalid Policy Schema: Missing keys {missing}")
        if not isinstance(data["banned_nodes"], list):
            raise PolicyValidationError("Schema Error: 'banned_nodes' must be a list.")

    def reload_policy(self):
        if not os.path.exists(self.policy_path):
            raise FileNotFoundError(f"Policy file missing: {self.policy_path}")
        
        current_mtime = os.path.getmtime(self.policy_path)
        if current_mtime > self.last_mtime:
            with open(self.policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.validate_schema(data)
            self.policy_data = data
            self.last_mtime = current_mtime
            print(f"[HOT-RELOAD] Applied Policy: {data['policy_name']} (v{data['version']})")

    def inspect_code(self, code):
        self.reload_policy()
        parsed = ast.parse(code)
        violations = []
        
        for node in ast.walk(parsed):
            if type(node).__name__ in self.policy_data["banned_nodes"]:
                violations.append(f"Banned Node: {type(node).__name__}")
            elif isinstance(node, ast.Name) and node.id in self.policy_data["banned_names"]:
                violations.append(f"Forbidden System Call: {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in self.policy_data["banned_attributes"]:
                violations.append(f"Forbidden Attribute Access: {node.attr}")
                
        return violations

if __name__ == "__main__":
    engine = LivePolicyEngine()
    test_attack = "import os"
    issues = engine.inspect_code(test_attack)
    print(f"Inspection Result for '{test_attack}': {issues}")
