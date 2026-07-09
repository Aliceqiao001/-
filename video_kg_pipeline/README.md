# 实验视频知识图谱构建 Pipeline

把 reactor 实验视频的语音讲解转成结构化知识（三元组），并用视频关键帧做视觉验证，最终产出"文本知识 + 图像证据"绑定的知识图谱。

## 目录结构

```
D:\视频解析\
├── .env                          # 共享密钥配置（三个 key + base_url，见下）
└── video_kg_pipeline\
    ├── config.py                 # 所有路径/模型名/重试策略的集中配置
    ├── stage1_asr.py              # 阶段一：抽音轨 + ASR 转写
    ├── stage1b_correct_terminology.py  # 阶段一之后：术语/单位纠错
    ├── stage2_extract.py          # 阶段二：三元组抽取 (GPT-4o)
    ├── stage3_keyframes.py        # 阶段三：关键时间点定位
    ├── stage4_visual.py           # 阶段四：seek 抽帧 + Gemini 视觉理解
    ├── stage5_bind.py             # 阶段五：图文绑定 + 冲突检测
    ├── stage6_visualize_kg.py     # 阶段六（可选）：三元组转图结构 + 可视化
    ├── run_pipeline.py            # 串联入口
    ├── utils\
    │   ├── llm_client.py          # OpenAI/Gemini 客户端构造 + 统一重试
    │   ├── video_utils.py         # ffmpeg 音轨抽取 + seek-based 抽帧
    │   └── io_utils.py            # JSON 读写
    ├── terminology\
    │   └── terminology_dict.json  # 术语/单位纠错词典，手动维护，改它不用改代码
    ├── outputs\                   # 所有阶段的产出（已生成，可直接查看）
    │   ├── 01_transcript.json
    │   ├── 01b_transcript_corrected.json  # 纠错后的转录，阶段二默认读这份
    │   ├── 02_triples.json
    │   ├── 03_keyframe_timestamps.json
    │   ├── 04_visual_evidence.json
    │   ├── 05_knowledge_graph.json
    │   ├── knowledge_graph.png    # 阶段六：静态图
    │   ├── knowledge_graph.html   # 阶段六：交互式图
    │   ├── frames\                # 抽出的关键帧图片
    │   └── audio\                 # 抽出的音频分片缓存
    └── requirements.txt
```

## 环境与依赖

- Python 3.10+（本机用的是 `C:\Users\HUAWEI\AppData\Local\Programs\Python\Python310\python.exe`）
- 依赖：`pip install -r requirements.txt`（openai、google-genai、python-dotenv、numpy、imageio-ffmpeg）
- **不需要**系统安装 ffmpeg：`imageio-ffmpeg` 自带静态二进制，`utils/video_utils.py` 会自动定位它。

## API Key 说明

三个 key 都放在根目录 `D:\视频解析\.env` 里，全部来自同一个国内大模型聚合网关 **VectorEngine**（`https://api.vectorengine.cn/v1`，OpenAI 协议兼容）：

| 变量 | 用途 | 使用的模型 |
|---|---|---|
| `ASR_API_KEY` | 阶段一语音转写 | `whisper-1` |
| `OPENAI_API_KEY` | 阶段二三元组抽取、阶段五冲突判断 | `gpt-4o` |
| `GEMINI_API_KEY` | 阶段四关键帧视觉理解 | `gemini-2.5-flash`（key 本身限定只能访问 gemini 系列模型） |

每个服务的 `*_BASE_URL` 也在 `.env` 里，默认已填好网关地址；模型名同样可以直接在 `.env` 里加 `OPENAI_MODEL`/`GEMINI_MODEL`/`ASR_MODEL` 覆盖，不用改代码。

## 怎么跑

```bash
cd video_kg_pipeline

# 完整跑一遍五个阶段（默认 TEST_MODE=1，只处理视频前 120 秒，见 .env 的 TEST_CLIP_SECONDS）
python run_pipeline.py

# 只跑某一个阶段（调试用，复用上一阶段已落盘的中间结果）
python run_pipeline.py --stage 3

# 从某一阶段开始跑到结束
python run_pipeline.py --from-stage 3

# 处理整段视频（忽略 TEST_MODE，跑完阶段一到五后自动追加阶段六生成可视化图）
python run_pipeline.py --full

# 只(重新)生成可视化图（复用已有的 05_knowledge_graph.json，不重新调用任何 API）
python run_pipeline.py --stage 6
```

也可以单独直接跑每个脚本，比如 `python stage2_extract.py`。阶段一之后会自动紧接着跑术语纠错（没有单独的 `--stage` 编号，因为它是阶段一产出的固定后处理，不是一个可独立跳过的阶段）；只想重新套用词典而不重新转写，可以单独跑 `python stage1b_correct_terminology.py`。

确认前 120 秒的效果没问题后，把 `.env` 里 `TEST_MODE=0`（或用 `--full`）跑全量视频。全量视频较长时，阶段一会自动按 15 分钟一片分段转写（避免单次上传超过 ASR 接口的文件大小限制），阶段二/三/四/五不需要额外改动。

## 各阶段输出字段说明

### `01_transcript.json`（阶段一）
```json
[{"index": 0, "text": "...", "start_ts": 0.0, "end_ts": 9.2}]
```
带时间戳的转写片段，来自 Whisper 的 `verbose_json` 分段结果（秒为单位）。

### `01b_transcript_corrected.json`（阶段一之后，术语纠错）
```json
{"index": 4, "text": "is 0.2 millimeter and ...", "start_ts": 55.88, "end_ts": 63.6, "original_text": "is 0.2 micrometer and ..."}
```
在 `01_transcript.json` 基础上跑一遍 `terminology/terminology_dict.json` 里的词典做替换：
- `corrections`（专有名词/拼写）：先精确匹配（大小写不敏感），找不到再退化成模糊匹配（`difflib` 相似度 ≥ 0.82），因为 ASR 每次识别错的拼法不一定完全一样。
- `unit_corrections`（单位）：只在 `context_hint`（比如 "gasket thickness"）**出现之后**才纠正紧跟着的 `wrong_unit`，不是全文无差别替换。这是必须的——同一份转录里 "particle size ... 600 to 800 micrometer" 是对的，"catalysis loading is 3 micrometer per centimeter square" 也跟垫片/腔室厚度无关，如果不分场景直接把所有 `micrometer` 换成 `millimeter` 会连累这些正确或者跟词典条目无关的值。考虑到 Whisper 经常把"腔室厚度是 / 10 微米"这种话从中间切成两段，纠错时会先在当前片段里找单位，找不到再看下一段。
- `original_text` 字段保留纠错前的原始 ASR 文本，方便追溯对照。
- 阶段二（`stage2_extract.py`）默认优先读这个文件，只有它不存在时才回退读 `01_transcript.json`。

**以后遇到新的识别错误（跑 R1-R6 等其他反应釜视频时），只需要往 `terminology/terminology_dict.json` 里加一条，不用碰任何代码**：
- 专有名词/型号识别错 -> 加进 `corrections`，`category` 随便写个标签方便自己归类（membrane/catalyst/...都行，不影响逻辑）。
- 单位识别错 -> 加进 `unit_corrections`，`context_hint` 尽量写该数值前面那个"这是什么参数"的短语（如 "gasket thickness"），避免写太泛的词（比如单独写 "thickness" 可能会连带误改到不相关的厚度值）。

（注：任务里建议放在 `config/terminology_dict.json`，实际放到了 `terminology/terminology_dict.json` —— 因为项目根目录已经有一个 `config.py` 模块，再建一个 `config/` 目录会跟它同名冲突，`import config` 会被目录优先解析导致所有脚本读配置都出错，所以换了个不冲突的目录名。）

### `02_triples.json`（阶段二）
```json
{"triple": ["cathode gasket", "has thickness", "0.2 micrometer"], "text_evidence": "...", "timestamp": [32.24, 59.08]}
```
GPT-4o 对相邻转录片段窗口做实体/关系抽取；`timestamp` 是支持该三元组的转录片段时间范围，`text_evidence` 直接取自原始转录文本（不是模型生成的，避免幻觉）。

### `03_keyframe_timestamps.json`（阶段三）
```json
{"timestamp": 45.66, "sources": ["triple"], "triple": [...], "text_evidence": "...", "matched_keywords": []}
```
候选时间点来自三个来源并合并去重（`sources` 字段标注命中了哪些来源）：
- `triple`：每条三元组时间区间的中点
- `keyword`：命中动作/状态变化词（start/appear/become/place/form...）的片段起点
- `semantic_shift`：相邻片段 embedding 余弦相似度骤降的位置（可选，若 embedding 调用失败会自动跳过，不影响其他两种来源）

### `04_visual_evidence.json`（阶段四）
```json
{"timestamp": 45.66, "frame_path": "outputs/frames/frame_0045.66.jpg", "text_context": "...", "vlm_description": "...", "triple": [...]}
```
用 ffmpeg seek 方式（`-ss` 放在 `-i` 前，快速跳转而非逐帧解码）在该时间点抽帧，Gemini 针对当时的文本主张做**针对性**视觉验证（不是泛泛描述画面）。

### `05_knowledge_graph.json`（阶段五，最终产出）
```json
{
  "triple": ["cathode gasket", "has thickness", "0.2 micrometer"],
  "text_evidence": "...",
  "image_evidence": {"frame_path": "...", "vlm_description": "..."},
  "timestamp": [32.24, 59.08],
  "confidence": 0.9,
  "conflict": false,
  "conflict_explanation": ""
}
```
- `confidence`：启发式打分，0.9=三元组与视觉证据是同一来源精确绑定，0.75=时间落在三元组区间内但非精确绑定，0.5=只能找到最近的帧，0.3=检测到冲突。
- `conflict`/`conflict_explanation`：由 GPT-4o 单独判断文本与图像描述是否**真的矛盾**（如"文本说变红但图像说变黄"），而不是"图像无法验证一个微米级测量值"这种正常的能力局限——后者不算冲突，只是降低 confidence。冲突不会被静默丢弃，节点会保留并标注说明。

### `knowledge_graph.png` / `knowledge_graph.html`（阶段六，可选）

把 `05_knowledge_graph.json` 的扁平三元组列表转成 `networkx.MultiDiGraph`：`subject`/`object` 是节点（同名实体自动合并，不会重复创建），`relation` 是边。

- **节点分类上色**：按实体名关键词分成阴极/阳极/中间腔室/气体参数/其他五类（`stage6_visualize_kg._classify`），静态图和交互图配色一致。
- **边的粗细/深浅 = confidence**：越粗、颜色越深，代表该三元组与视觉证据的绑定越可信；具体映射见 `CONFIDENCE_BY_MATCH`/`_confidence_color`。
- **`conflict: true` 的边是虚线 + 中性标注**（"narration lag"/"动作滞后于讲解"），**不用红色或警告样式**——结合前面五个阶段的结论，这批冲突本质是"叙述先于/晚于动作发生"的正常时间差，不是真正的图文矛盾，所以视觉上刻意跟"数据有问题"区分开。
- **静态图的布局是关键坑**：这份知识图谱高度碎片化（24 条三元组分散在 16 个互不相连的连通分量里，多数是孤立的"主语→宾语"两节点对），直接对全图跑 `spring_layout`/`kamada_kawai_layout` 会导致节点乱挤或乱飞。`stage6_visualize_kg._layout_by_component` 按连通分量单独布局、再平铺到网格上，并加了一个最小间距的后处理（`_resolve_overlaps`）防止两个互相连接的"枢纽"节点被拉到重合。
- **交互图**（pyvis + vis.js）支持拖拽、缩放、悬停节点/边看详情；边的悬停提示包含 `relation`/`confidence`/`timestamp`/`text_evidence` 摘要和对应的 `frame_path`（vis.js 的 tooltip 支持 HTML，但没有再额外嵌入 `<img>` 预览图，只展示路径文字——保持简单、确保一定能正常显示）。图的核心引擎（vis-network）已内联进 HTML，可离线打开；页面外层的 Bootstrap 样式仍走 CDN，没有网络时图本身照常可用，只是外层卡片样式会退化成无样式。

## 已知限制 / 后续可扩展点

- 三元组抽取按固定窗口（5 段转录片段）切分，长视频可考虑按语义段落自适应分窗。
- 冲突检测和三元组抽取共用 `gpt-4o`，成本敏感场景可以把冲突检测换成更便宜的模型。
- 若之后要并入更大的多阶段 pipeline，`config.py` 里的路径/模型名/`VIDEO_PATH` 都可通过环境变量覆盖，无需改代码；每个 `stageN_*.py` 都暴露了 `run()` 函数可以直接被其他脚本 import 调用。
