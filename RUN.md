# 快速运行（5 分钟）

## 0. 前置条件

- Python 3.10+
- 一个 DeepSeek API Key（抽取用）：https://platform.deepseek.com
- 一个第二家模型的 Key（审核用，三选一）：
  - 阿里通义千问 DashScope（有免费额度）
  - 智谱 GLM（有免费额度）
  - 或者没有第二家时，退化用 DeepSeek 的另一个模型（见下文「只用一个 Key」）

---

## 1. 安装依赖

```bash
cd mining-extract-agent
python -m pip install -r requirements.txt
```

---

## 2. 配置密钥

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

编辑 `.env`，至少填这两项：

```ini
EXTRACTOR_API_KEY=sk-你的DeepSeekKey
CRITIC_API_KEY=sk-你的审核模型Key
```

### 只用一个 Key 的退化方案

没有第二家模型时，把审核也指向 DeepSeek，但**换一个模型**：

```ini
CRITIC_BASE_URL=https://api.deepseek.com
CRITIC_API_KEY=sk-同一个DeepSeekKey
CRITIC_MODEL=deepseek-v4-pro
```

> 这仍然满足「换一个模型来挑刺」的核心要求（不同参数量的模型，
> 判断偏差已经足够形成对抗），但**优先推荐用不同厂商的模型**，
> 因为跨厂商的偏差更大，审核价值更高。

---

## 3. 放入报告 PDF

把 NI 43-101 / 技术报告 PDF 放进 `data/pdfs/`。

仓库里已经带了一份**合成样例** `SAMPLE_43-101_ExampleGold.pdf`，
用于在没有真实报告时验证流水线是否通畅。

---

## 4. 运行

```bash
# 跑 data/pdfs/ 下全部 PDF
python main.py run

# 只跑某一份
python main.py run --pdf data/pdfs/xxx.pdf
```

**你会看到：**

```
[xxx] 共 214 页，命中资源量相关页 7 页
[xxx] 第 1/3 轮抽取 ...
[xxx] 抽到 2 行，送审核 ...
[xxx] 审核得分 9/10，问题 0 条
...
============================================================
结果汇总
============================================================
  xxx    通过    轮数=1 最高分=9
明细已写入：outputs/result.json
```

---

## 5. 评测

先填好 `data/ground_truth.json`，然后：

```bash
python eval/evaluate.py
```

输出：

```
容差            : ±5%
字段级 accuracy : 87.50%
abstain 统计     : 正确拒答 1 | 漏报 0 | 幻觉 0
```

---

## 6. 查看进化日志

```bash
python main.py stats
```

`evolution.jsonl` 里逐行记录了每次抽取 / 审核的结果，
可用于分析「哪类报告容易抽错」「哪一轮改进最有效」。

---

## 常见问题

**Q: 报错「缺少环境变量：EXTRACTOR_API_KEY」**
A: `.env` 没建或没填。检查项目根目录下是否存在 `.env`。

**Q: 报错 JSON 解析失败**
A: 模型没按格式返回。本项目已做三级兜底（直接解析 / 剥代码块 / 取首尾大括号），
若仍失败，检查该模型是否支持 `response_format={"type":"json_object"}`。

**Q: 一直 abstain**
A: 两种可能：① PDF 是扫描件，没有文字层（当前不支持 OCR）；
② 报告确实没有资源量表，此时 abstain 是**正确行为**。

**Q: 跑得慢 / 花太多钱**
A: 减少 `src/pdf_utils.py` 里 `locate_resource_pages(top_k=6)` 的 top_k；
或把 `MAX_ROUNDS` 调到 2。
