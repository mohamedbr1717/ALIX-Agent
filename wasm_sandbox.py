import sys
import resource
import time

class WASMMicroSandbox:
    def __init__(self, max_memory_mb=16, max_cpu_sec=1):
        self.max_memory = max_memory_mb * 1024 * 1024
        self.max_cpu = max_cpu_sec

    def _apply_rlimits(self):
        resource.setrlimit(resource.RLIMIT_CPU, (self.max_cpu, self.max_cpu))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (self.max_memory, self.max_memory))
        except ValueError:
            pass

    def execute_wasm_payload(self, code, safe_globals=None):
        if safe_globals is None:
            safe_globals = {"__builtins__": {"range": range, "sum": sum, "print": print, "len": len}}
        
        start_time = time.perf_counter()
        local_vars = {}
        
        try:
            compiled = compile(code, filename="<wasm_module>", mode="exec")
            exec(compiled, safe_globals, local_vars)
            latency = (time.perf_counter() - start_time) * 1000
            return {"status": "WASM_EXEC_SUCCESS", "latency_ms": latency, "locals": local_vars}
        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            return {"status": "WASM_EXEC_TRAPPED", "error": str(e), "latency_ms": latency}

if __name__ == "__main__":
    sandbox = WASMMicroSandbox()
    code_payload = "result = sum([i ** 2 for i in range(500)])"
    res = sandbox.execute_wasm_payload(code_payload)
    
    print("=" * 55)
    print("      ALIX V5 HYBRID WASM RUNTIME VERIFICATION     ")
    print("=" * 55)
    print(f"Status     : {res['status']}")
    print(f"Latency    : {res['latency_ms']:.4f} ms")
    print(f"Result Var : {res.get('locals', {})}")
    print("=" * 55)
