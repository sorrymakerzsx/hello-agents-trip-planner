# 旅行规划测试集与性能评测

测试用例保存在 `test_cases.json`，覆盖不同城市、天数、偏好和额外要求。

## 离线评测

不调用 LLM、地图或天气 API，只验证数据结构和评估统计流程：

```powershell
cd backend
python evals/evaluate_dataset.py
```

输出包括：

- 成功率和失败数；
- 平均延迟；
- P95 延迟；
- 平均质量得分；
- 每个用例的检查结果。

## 真实端到端评测

```powershell
cd backend
python evals/evaluate_dataset.py --live
```

该模式会真实调用 LLM 和地图服务，可能消耗 API 配额，建议只在需要测量真实耗时时运行。

推荐记录多次运行结果，再比较 Harness 改造前后的：

```text
success_rate
average_latency_ms
p95_latency_ms
average_score
agent_metrics.parallel_phase_time
```
