import hashlib
import random
from typing import Any, Dict, List

from saki_runtime.core.client import saki_client
from saki_runtime.schemas.ir import SampleIR
from saki_runtime.schemas.query import QueryCandidate, QueryRequest


class QueryService:
    async def query_samples(self, request: QueryRequest) -> List[QueryCandidate]:
        # 1. Fetch unlabeled samples
        # Limit total samples to process to avoid OOM or timeout in MVP
        max_images = request.params.get("max_images", 5000)
        
        samples: List[SampleIR] = []
        count = 0
        
        async for sample in saki_client.iter_unlabeled_samples(
            request.source_commit_id
        ):
            samples.append(sample)
            count += 1
            if count >= max_images:
                break

        # 2. Score samples
        candidates = []
        for sample in samples:
            score, reason = await self._calculate_score(sample, request)
            candidates.append(QueryCandidate(
                sample_id=sample.id,
                score=score,
                reason=reason
            ))

        # 3. Sort and TopK
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:request.topk]

    async def _calculate_score(self, sample: SampleIR, request: QueryRequest) -> tuple[float, Dict[str, Any]]:
        """
        Calculate score for a sample.
        Higher score means more informative (should be selected).
        For uncertainty sampling, score = 1 - confidence (or entropy).
        """
        # MVP: Pseudo scoring
        # In real implementation, this would call a Scorer (loaded from plugin)
        # to run inference on sample.uri
        
        # Deterministic pseudo score based on sample ID hash
        h = hashlib.md5(sample.id.encode()).hexdigest()
        pseudo_conf = int(h, 16) % 100 / 100.0

        if request.strategy == "uncertainty":
            score = 1.0 - pseudo_conf
            reason = {
                "strategy": "uncertainty",
                "max_conf": pseudo_conf,
                "score": score,
            }
        elif request.strategy == "iou_diff":
            # Pseudo IOU diff score
            pseudo_iou = (int(h, 16) % 80) / 100.0
            score = 1.0 - pseudo_iou
            reason = {
                "strategy": "iou_diff",
                "iou": pseudo_iou,
                "score": score,
            }
        else:
            random.seed(sample.id)
            score = random.random()
            reason = {"strategy": "random", "score": score}
            
        return score, reason

query_service = QueryService()
