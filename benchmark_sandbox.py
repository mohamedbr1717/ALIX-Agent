import time
import tracemalloc

try:
    from core.alix_v4_complete import ASTSandbox
except ImportError:
    import ast
    class ASTSandbox:
        def validate_and_execute(self, code):
            parsed = ast.parse(code)
            exec(compile(parsed, filename="<ast>", mode="exec"))

def run_empirical_benchmark(iterations=1000):
    sandbox = ASTSandbox()
    test_payload = "x = sum([i ** 2 for i in range(100)])"
    
    tracemalloc.start()
    start_time = time.perf_counter()
    
    for _ in range(iterations):
        sandbox.validate_and_execute(test_payload)
        
    end_time = time.perf_counter()
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    total_time = end_time - start_time
    avg_latency_ms = (total_time / iterations) * 1000
    peak_mem_kb = peak_mem / 1024
    
    print("=" * 45)
    print("      ALIX V4 EMPIRICAL BENCHMARK REPORT     ")
    print("=" * 45)
    print(f"Total Executions : {iterations}")
    print(f"Total Time       : {total_time:.4f} s")
    print(f"Mean Latency     : {avg_latency_ms:.4f} ms/op")
    print(f"Peak Memory      : {peak_mem_kb:.2f} KB")
    print("=" * 45)

if __name__ == "__main__":
    run_empirical_benchmark()
