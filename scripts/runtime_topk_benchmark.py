from __future__ import annotations

import heapq
import random
import time
import tracemalloc


def streaming_topk(sample_count: int, topk: int) -> list[tuple[float, str]]:
    heap: list[tuple[float, int, str]] = []
    counter = 0
    rng = random.Random(20260207)

    for idx in range(sample_count):
        sample_id = f"s{idx}"
        score = rng.random()
        counter += 1
        payload = (score, counter, sample_id)
        if len(heap) < topk:
            heapq.heappush(heap, payload)
        else:
            if score > heap[0][0]:
                heapq.heapreplace(heap, payload)

    ranked = sorted(heap, key=lambda item: item[0], reverse=True)
    return [(score, sample_id) for score, _, sample_id in ranked]


def main() -> None:
    sample_count = 100_000
    topk = 200

    tracemalloc.start()
    start = time.perf_counter()
    result = streaming_topk(sample_count=sample_count, topk=topk)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"samples={sample_count} topk={topk} elapsed_ms={elapsed_ms:.2f} peak_mem_mb={peak / 1024 / 1024:.2f}")
    print(f"best_sample={result[0][1]} best_score={result[0][0]:.6f}")


if __name__ == "__main__":
    main()
