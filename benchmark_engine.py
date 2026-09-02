import time
import tracemalloc
import statistics
from test_sample import safe_eval, SafeEvalError

def benchmark_eval_speed(iterations=10000):
    expressions = [
        "1 + 2 * 3",
        "(100 + 200) * 3 / 5",
        "10 == 10 and 5 > 2",
        "100 ** 2 + 50 - 20",
        "True or False and True"
    ]
    
    latencies = []
    tracemalloc.start()
    start_time = time.perf_counter()
    
    for _ in range(iterations):
        for expr in expressions:
            t0 = time.perf_counter()
            safe_eval(expr)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)

    total_time = time.perf_counter() - start_time
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print("=== AST SAFE EVALUATION BENCHMARK ===")
    print(f"Total Evaluated Expressions : {iterations * len(expressions)}")
    print(f"Total Execution Time        : {total_time:.4f} s")
    print(f"Throughput                  : {(iterations * len(expressions)) / total_time:.2f} ops/sec")
    print(f"Average Latency             : {statistics.mean(latencies):.5f} ms")
    print(f"Median Latency              : {statistics.median(latencies):.5f} ms")
    print(f"P99 Latency                 : {sorted(latencies)[int(len(latencies)*0.99)]:.5f} ms")
    print(f"Peak Memory Overhead        : {peak_mem / 1024:.2f} KB")

def benchmark_dos_rejection():
    deep_expr = "- " * 35 + "1"
    start_time = time.perf_counter()
    rejected = False
    try:
        safe_eval(deep_expr)
    except SafeEvalError:
        rejected = True
    latency = (time.perf_counter() - start_time) * 1000
    
    status = "PASSED" if rejected else "FAILED"
    print("\n=== SECURITY DoS REJECTION BENCHMARK ===")
    print(f"Deep AST Attack Rejection Latency : {latency:.5f} ms")
    print(f"Protection Status                 : {status}")

if __name__ == "__main__":
    benchmark_eval_speed()
    benchmark_dos_rejection()
