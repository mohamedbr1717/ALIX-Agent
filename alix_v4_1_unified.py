import time
from policy_watcher import LivePolicyEngine
from vector_memory import LightweightVectorStore

class ALIXv41Agent:
    def __init__(self, policy_path="policy.json"):
        self.policy_engine = LivePolicyEngine(policy_path)
        self.memory = LightweightVectorStore()
        print("[ALIX v4.1] Agent Core Initialized Successfully.")

    def store_context(self, mem_id, text):
        self.memory.add_document(mem_id, text)

    def execute_task(self, task_code, context_query=None):
        start_time = time.perf_counter()
        
        # 1. استرجاع السياق المتجهي
        context_result = []
        if context_query:
            context_result, _ = self.memory.search(context_query, top_k=1)
            
        # 2. الفحص الديناميكي لجدار حماية AST
        violations = self.policy_engine.inspect_code(task_code)
        
        latency = (time.perf_counter() - start_time) * 1000
        
        if violations:
            return {
                "status": "BLOCKED",
                "violations": violations,
                "latency_ms": latency,
                "context": context_result
            }
            
        return {
            "status": "APPROVED",
            "violations": [],
            "latency_ms": latency,
            "context": context_result
        }

if __name__ == "__main__":
    agent = ALIXv41Agent()
    agent.store_context("ctx_1", "AST policy enforcement for dynamic code analysis")
    
    # تجربة تنفيذ كود آمن
    res1 = agent.execute_task("x = [i**2 for i in range(10)]", "AST policy")
    print(f"\n[TEST 1 - Clean Code] Status: {res1['status']} | Latency: {res1['latency_ms']:.4f} ms")
    
    # تجربة تنفيذ كود ينتهك السياسة
    res2 = agent.execute_task("import os; os.system('ls')", "policy enforcement")
    print(f"[TEST 2 - Malicious Code] Status: {res2['status']} | Violations: {res2['violations']}")
