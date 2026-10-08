# NI 43-101 资源量抽取 · 对抗审核框架

> 题目 #3：「对抗审核」— 从 NI 43-101 矿权报告 PDF 中自动抽取
> Indicated / Inferred 资源量（矿石量 · 品位 · 金属量），
> 并用**另一个模型**挑刺评分，不超过阈值就拒答。

---

## 一、题目要求对照

| 题目要求 | 本仓库实现 | 位置 |
|---|---|---|
| Extractor Agent：强模型抽取 | DeepSeek 抽取，强制给「页码 + 原文引用」 | `src/extractor.py` |
| CriticMaster Agent：另一个模型挑刺，评分 1-10 | 可配 Qwen / GLM / DeepSeek 另一模型 | `src/critic.py` |
| Revise Loop：≤3 轮，≥8 分通过，否则 abstain | 轮数耗尽**返回 abstain 而非最后一次结果** | `src/loop.py` |
| Evolution Log：失败 case 自动 append | JSON Lines 追加 + 复盘统计 | `src/evolution.py` |
| 评分协议：字段级 accuracy（±5%） | 相对误差比对 + abstain 正确性单列 | `eval/evaluate.py` |

---

## 二、核心设计

### 1. 为什么不做表格解析，而是「文本 + 原文引用」

NI 43-101 的资源量表格版式差异极大：跨页、合并单元格、脚注混排、单位混用（Mt / t / oz）。
硬解析表格的鲁棒性远低于「把相关页文本交给模型 + 强迫它给出原文引用」。

因此本项目的证据链是：**每个数值字段都必须能追溯到某一页的某段原文**。
拿不出引用的行会被直接丢弃（`src/extractor.py: parse_extraction`）。

### 2. 为什么审核必须换一个模型

同一个模型既当运动员又当裁判，会系统性高估自己。
跨模型审核能显著暴露「数字看着对、其实是从相邻项目抄来的」这类错误。

配置里 `CRITIC_MODEL` 与 `EXTRACTOR_MODEL` 强制分离，且可以用完全不同的厂商（Qwen / GLM）。

### 3. 最关键的取舍：宁可交白卷，不要硬给

题目原文：

> 我们最看的是：**当抽取明显错误时，系统是否 abstain 而不是硬给**

对应实现有三道闸门：

| 闸门 | 触发条件 | 结果 |
|---|---|---|
| 抽取端 | 模型自己判断证据不足 | `abstain=true`，不进入审核 |
| 审核端 | 审核模型认为应拒答 | 直接判不通过 |
| 循环端 | 3 轮后仍未达 8 分 | **丢弃全部抽取结果**，返回 `abstain + 转人工` |

第三道最容易写错：很多实现会在轮数耗尽时返回「最后一次的抽取结果」——
那恰好是题目要防的「硬给」。本实现显式丢弃（`src/loop.py: run_one` 末尾）。

---

## 三、目录结构

```
mining-extract-agent/
├── main.py                  # 命令行入口（run / stats）
├── requirements.txt
├── .env.example             # 密钥模板（不含真实密钥）
├── src/
│   ├── config.py            # 集中配置，全部来自环境变量
│   ├── schemas.py           # 数据模型（区分「缺失」与「为 0」）
│   ├── pdf_utils.py         # PDF 解析 + 资源量页定位
│   ├── llm.py               # 统一 LLM 调用（OpenAI 兼容）
│   ├── extractor.py         # Extractor Agent
│   ├── critic.py            # CriticMaster Agent
│   ├── loop.py              # Revise Loop
│   └── evolution.py         # Evolution Log
├── eval/
│   └── evaluate.py          # 字段级 accuracy + abstain 统计
├── data/
│   ├── pdfs/                # 放 NI 43-101 PDF
│   └── ground_truth.json    # 人工核对的标准答案
├── outputs/                 # 抽取结果 + 评测报告
└── evolution.jsonl          # 每次尝试的流水（自动生成）
```

---

## 四、快速开始

见 [RUN.md](RUN.md)。

---

## 五、评测结果（真实报告实测）

三份真实技术报告 + 一份合成样例 + 一份「无资源量表」的负例：

| 报告 | 来源 | 字段级 accuracy | 轮数 | 审核分数 | 结果 |
|---|---|---|---|---|---|
| Carlin-TR-12312024 | Newmont，338 页 | **100%** | 2 | 7 → 9 | 通过 |
| Barrick_PuebloViejo | Barrick NI 43-101，301 页 | **100%** | 1 | 9 | 通过 |
| SAMPLE_43-101 | 合成样例，3 页 | **100%** | 1 | 9 | 通过 |
| Pilbara_Minerals-CP | Pilbara，28 页 | — | 1 | — | **正确 abstain** |

**整体字段级 accuracy：100.00%（容差 ±5%）**
**abstain 统计：正确拒答 1 | 漏报 0 | 幻觉 0**

抽取实例（均可回溯到原文页码）：

| 报告 | 类别 | 矿石量 | 品位 | 金属量 | 页码 |
|---|---|---|---|---|---|
| Carlin | Indicated | 230 Mt | 3.43 g/t Au | 25 Moz | p190 |
| Carlin | Inferred | 78 Mt | 3.70 g/t Au | 9.3 Moz | p190 |
| Barrick | Indicated | 300 Mt | 1.82 g/t Au | 18 Moz | p17 |
| Barrick | Inferred | 16 Mt | 1.50 g/t Au | 0.77 Moz | p17 |

**Pilbara 那份 abstain 是正确的** —— 该 PDF 只有合规声明和项目概况，
通篇没有资源量表。系统没有编数字，而是拒答并转人工。

---

## 六、调试过程中发现的四个真问题

这一节是本次作业最有价值的部分：**下面每一条都是先在真实报告上失败、定位原因后才修好的。**

### 问题 1：目录页骗过了关键词匹配

Newmont Ahafo 报告 439 页，纯关键词打分把 **图表清单页** 排到最高分 ——
它包含 "Table 1-1: Measured and Indicated Mineral Resource Statement" 这样的完整表名，
关键词全中，**却一个数字都没有**。

**修复**：加入「目录页特征」（大量点线引导符 / 密集 Table x-y 交叉引用）直接判零分。

### 问题 2：数字密度高的页不一定是资源表

Barrick Pueblo Viejo 报告 301 页。改用数字密度后，
**冶金与工厂性能表** 的数字比资源表还多，于是真正的资源表被挤到第 8、9 名之外，直接漏掉。

**修复**：改以「资源表专属措辞」为主信号（"Mineral Resource Statement"、
"Total Inferred"、"at a cut-off grade"、"Contained Metal" 等），数字密度只作弱加权。

### 问题 3：思考模式会吃光 token 预算

DeepSeek 系模型默认开启思考模式，**推理 token 与正文 token 共用同一额度**。
实测在 18 页上下文上：

| max_tokens | 结果 |
|---|---|
| 4096 | 推理吃光，正文为空 |
| 16384 | 推理仍吃光（reasoning_tokens=16384），正文为空 |

**修复**：通过 `extra_body={"thinking": {"type": "disabled"}}` 关闭思考模式（结构化抽取不需要推理链），
并在返回空内容时把 finish_reason 明确报出来，而不是只说「返回为空」。

**效果**：单份报告从 2-3 分钟降到 **5-20 秒**。

### 问题 4：抽取与审核对「抽哪张表」理解不一致

Carlin 报告里既有「矿区整体汇总表」，也有「各矿床分项表」。
抽取模型有时抽分项（10 行）、有时抽汇总（2 行），审核模型拿另一张表去核对，
两边永远谈不拢，最后误判 abstain。

**修复**：在抽取提示词里明确规定 —— **一律抽「项目/矿区整体」的汇总数字**，
不输出分项行；若只有分项表则在 reason 中说明。

> 值得强调的是：**审核模型本身也会错。** 某一轮审核坚持认为 Inferred 应为
> "42 Mt / 1.7 Moz"（那是某个矿床的分项），而原文第 190 页明确写着
> "78 Mt ... for 9.3 Moz"。系统最终 abstain 转人工，而不是盲从审核 ——
> 这正是题目要求的「不会硬给」。

---

## 七、成本与耗时

| 配置 | 单份耗时 | 说明 |
|---|---|---|
| 思考模式开启 | 2-3 分钟 | 每次调用先花 16000+ 推理 token |
| **思考模式关闭（默认）** | **5-20 秒** | 结构化抽取不需要推理链 |

单份报告的 API 成本约 **几分钱**（DeepSeek 空闲时段 1 元/百万 token 输入）。

关键开关都在 `.env`：

```ini
THINKING_ENABLED=false   # 关闭思考模式，省 90% 时间
TOP_K_PAGES=6            # 喂给模型的页数（实测下限，降到 3 会漏掉关键页）
MAX_CONTEXT_CHARS=40000  # 上下文字符上限
MAX_ROUNDS=3             # 对抗循环上限
```

---

## 八、局限与后续

1. **扫描版 PDF 不支持** —— 当前依赖 PyMuPDF 的文字层；纯图片型报告需要先接 OCR。
2. **表格跨页断行** —— 资源量表常跨两页，靠关键词窗口（前后各 1 页）覆盖，极端版式仍可能漏。
3. **单位归一化不完整** —— 目前只做文本比对，未做 oz ↔ t、% ↔ g/t 的自动换算。
4. **few-shot 自改进未闭环** —— `evolution.jsonl` 已完整记录失败 case，
   但「自动挑样本回填提示词」这一步是人工的（题目也只要求分析，未要求自动回填）。