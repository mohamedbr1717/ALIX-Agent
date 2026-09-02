import math
import time
from collections import Counter

class LightweightVectorStore:
    def __init__(self):
        self.documents = []
        self.vocab = set()
        self.doc_vectors = []

    def _tokenize(self, text):
        return [w.lower() for w in text.split() if w.isalnum()]

    def add_document(self, doc_id, text):
        tokens = self._tokenize(text)
        self.documents.append({"id": doc_id, "text": text, "tokens": tokens})
        self.vocab.update(tokens)
        self._reindex()

    def _reindex(self):
        vocab_list = sorted(list(self.vocab))
        self.doc_vectors = []
        N = len(self.documents)
        
        idf = {}
        for term in vocab_list:
            df = sum(1 for doc in self.documents if term in doc["tokens"])
            idf[term] = math.log((N + 1) / (df + 1)) + 1

        for doc in self.documents:
            tf = Counter(doc["tokens"])
            total_words = len(doc["tokens"]) or 1
            vec = [(tf[term] / total_words) * idf[term] for term in vocab_list]
            norm = math.sqrt(sum(v ** 2 for v in vec)) or 1.0
            self.doc_vectors.append([v / norm for v in vec])

    def search(self, query, top_k=2):
        start = time.perf_counter()
        q_tokens = self._tokenize(query)
        vocab_list = sorted(list(self.vocab))
        
        q_tf = Counter(q_tokens)
        q_vec = [q_tf[term] for term in vocab_list]
        q_norm = math.sqrt(sum(v ** 2 for v in q_vec)) or 1.0
        q_vec_norm = [v / q_norm for v in q_vec]

        scores = []
        for idx, d_vec in enumerate(self.doc_vectors):
            sim = sum(q * d for q, d in zip(q_vec_norm, d_vec))
            scores.append((sim, self.documents[idx]))

        scores.sort(key=lambda x: x[0], reverse=True)
        latency_ms = (time.perf_counter() - start) * 1000
        return scores[:top_k], latency_ms

if __name__ == "__main__":
    store = LightweightVectorStore()
    store.add_document("mem_1", "Execute AST sandbox policy check for Python code")
    store.add_document("mem_2", "Database query optimization for user credentials")
    store.add_document("mem_3", "Vector memory indexer with cosine similarity retrieval")

    results, latency = store.search("AST policy check")
    print("=" * 55)
    print("    ALIX v4.1 VECTOR MEMORY RETRIEVAL BENCHMARK     ")
    print("=" * 55)
    print(f"Retrieval Latency : {latency:.4f} ms")
    print(f"Top Match ID      : {results[0][1]['id']}")
    print(f"Similarity Score  : {results[0][0]:.4f}")
    print("=" * 55)
