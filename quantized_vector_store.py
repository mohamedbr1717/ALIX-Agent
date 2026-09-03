import math
import time

class QuantizedVectorEngine:
    def __init__(self, vector_dim=64):
        self.dim = vector_dim
        self.documents = []

    def _pseudo_embed(self, text):
        vec = [0.0] * self.dim
        for i, char in enumerate(text.lower()):
            vec[ord(char) % self.dim] += (i + 1) * 0.05
        norm = math.sqrt(sum(v**2 for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _quantize_int8(self, float_vec):
        return [max(-128, min(127, int(round(v * 127)))) for v in float_vec]

    def add_document(self, doc_id, text):
        float_emb = self._pseudo_embed(text)
        int8_emb = self._quantize_int8(float_emb)
        self.documents.append({"id": doc_id, "text": text, "vector": int8_emb})

    def search(self, query, top_k=1):
        start = time.perf_counter()
        q_float = self._pseudo_embed(query)
        q_int8 = self._quantize_int8(q_float)

        results = []
        for doc in self.documents:
            dot_prod = sum(a * b for a, b in zip(q_int8, doc["vector"]))
            score = dot_prod / (127.0 * 127.0)
            results.append((score, doc))

        results.sort(key=lambda x: x[0], reverse=True)
        latency = (time.perf_counter() - start) * 1000
        return results[:top_k], latency

if __name__ == "__main__":
    engine = QuantizedVectorEngine()
    engine.add_document("doc1", "ALIX AST sandbox execution policy")
    engine.add_document("doc2", "Database query performance tuning")
    
    matches, latency = engine.search("AST sandbox policy execution")
    print("=" * 55)
    print("   ALIX V5 QUANTIZED VECTOR MEMORY VERIFICATION     ")
    print("=" * 55)
    print(f"Retrieval Latency : {latency:.4f} ms")
    print(f"Top Match ID      : {matches[0][1]['id']}")
    print(f"Quantized Score   : {matches[0][0]:.4f}")
    print("=" * 55)
