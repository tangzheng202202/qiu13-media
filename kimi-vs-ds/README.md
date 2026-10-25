# Kimi K3.1 Pro vs DeepSeek V4.1 Flash — 编程难题实测原始材料

- `prompts/`：喂给模型的原提示词（两边相同）
- `tasks/`：任务文件；`tasks/*/hidden_test.py` 是隐藏测试（t4 39 条、t5 19 条），agent 运行时不可见，结束后才放入
- `harness.py` / `harness_k.py` / `harness_ks.py`：agent 循环（工具 bash / write_file / read_file，MAXSTEPS=40）。`harness_ks.py` 只把 Kimi 请求改成 stream=True，用来避开服务端 5 分钟断连
- `logs/`：每次运行的汇总 JSON（`.log` / `.out`）和错误日志
- `runs/`：每次运行的完整对话 transcript、隐藏测试输出、模型生成的代码
- `results.md`：汇总表和成本算法（DeepSeek 非高峰价 $0.15/$0.003/$0.6，Kimi ¥13/¥1.30/¥68 每百万 token，1 USD≈7.2 CNY）

注：运行日志里没有成本字段，成本是用 token 数乘以官方单价算的；Kimi 未对 Moonshot 账单。
