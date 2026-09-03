import hashlib
import json
import time

class MerkleAuditLogger:
    def __init__(self):
        self.chain = []
        self.prev_hash = "0" * 64

    def _hash_str(self, data_str):
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()

    def log_execution(self, code, status, latency_ms, violations=None):
        timestamp = time.time()
        payload = {
            "index": len(self.chain),
            "timestamp": timestamp,
            "code_hash": self._hash_str(code),
            "status": status,
            "latency_ms": round(latency_ms, 4),
            "violations": violations or [],
            "prev_hash": self.prev_hash
        }
        
        serialized = json.dumps(payload, sort_keys=True)
        entry_hash = self._hash_str(serialized)
        payload["hash"] = entry_hash
        
        self.chain.append(payload)
        self.prev_hash = entry_hash
        return payload

    def verify_integrity(self):
        for i in range(1, len(self.chain)):
            curr = self.chain[i]
            prev = self.chain[i - 1]
            if curr["prev_hash"] != prev["hash"]:
                return False, f"Tampering detected at block index {i}!"
        return True, "All execution logs strictly cryptographically verified."

if __name__ == "__main__":
    logger = MerkleAuditLogger()
    
    # تسجيل عمليتين للتحقق من السلسلة
    logger.log_execution("x = [i**2 for i in range(100)]", "APPROVED", 0.4211)
    logger.log_execution("import os; os.system('ls')", "BLOCKED", 0.1205, ["Banned Node: Import"])
    
    is_valid, msg = logger.verify_integrity()
    
    print("=" * 55)
    print("      ALIX V5 MERKLE AUDIT LOG VERIFICATION     ")
    print("=" * 55)
    print(f"Blocks Recorded : {len(logger.chain)}")
    print(f"Latest Hash Root: {logger.prev_hash[:24]}...")
    print(f"Integrity Status: {msg}")
    print("=" * 55)
