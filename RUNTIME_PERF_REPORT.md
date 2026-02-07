# Runtime 性能基线报告（Phase 3）

## 1. 范围

本报告覆盖 Runtime 收敛三期计划中的 Phase 3 基线项：

1. active-learning TopK 聚合采用流式分页 + bounded min-heap。
2. 下载与上传链路改为流式传输，避免整文件入内存。

## 2. 基线脚本

脚本：`/Users/hhm/code/saki/scripts/runtime_topk_benchmark.py`

执行命令：

```bash
uv run python /Users/hhm/code/saki/scripts/runtime_topk_benchmark.py
```

## 3. 最近一次结果

执行时间：2026-02-07  
环境：本地开发机（Python 3.13 + uv）

```text
samples=100000 topk=200 elapsed_ms=166.87 peak_mem_mb=0.05
best_sample=s50838 best_score=0.999981
```

结论：

1. 10 万样本 TopK 聚合可在毫秒级完成，内存峰值随 `topk` 线性增长，与样本总量弱相关。
2. 现实现满足“单任务大样本打分时不全量驻留候选集”的目标。

## 4. 说明与后续

1. 该基线为算法聚合层数据，不包含真实模型推理耗时与网络波动。
2. 下一步建议在集成环境补充“真实 DataRequest 分页 + 插件推理”端到端压测报告。
