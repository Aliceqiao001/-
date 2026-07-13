# 设计逻辑文档 × 视频知识图谱 交叉对比报告

## 说明

- **对比材料**:
  - 文档:`R1-R2.docx`、`R2-R3_Claim_Ledger.docx` + `R2-R3_Evidence_Chain.docx`(R2-R3 阶段有两份文件,内容互补,合并作为一份"R2-R3 文档"处理)、`R3-R4_Evidence_Chain.docx`、`R4-R5_Evidence_Chain.docx`。四份文档路径均在 `1.Reactor_Agent/Claim Ledger/<Rx-Ry>/` 下,已逐一读取确认。
  - 视频知识:`outputs_batch/MASTER_KNOWLEDGE_LOG.md` 的逐视频叙述 + 对应实验文件夹的 `05_knowledge_graph.json` 原始三元组(文档中引用的三元组均标注来源视频文件夹)。
- **四档标注**:✅ Confirmed(一致)/ 🟡 Partially Confirmed(部分一致)/ ⬜ Not Covered(视频未覆盖)/ 🔴 Discrepancy(有出入)。
- **一个贯穿全篇的重要边界条件**:video_kg_pipeline 只提取视频里 narrator 的口头讲解(装配步骤、测试配置、拆解观察),**不处理 Echem 电化学原始数据(.mpr/CP/PEIS 数值)**。因此凡是文档里依赖"电压/阻抗数值下降"这类量化电化学证据的诊断,天然不可能在视频知识图谱里找到对应三元组——这不是流程缺陷,而是两种材料本身覆盖范围不同。下面每一处"失效诊断"维度的 Not Covered,基本都属于这类情况,会在各部分单独说明,并在末尾总结里统一点出。

---

## 一、R1 → R2

### 1. 结构描述比对(R1 结构,对照 `R1_1Cell_070`)

| 文档描述 | 视频知识图谱 | 结论 |
|---|---|---|
| "CuO/H23C3 cathode" | `['cathode electrode', 'prepared by', 'spray coating copper oxide catalysis onto H23C3 carbon paper']`(conf 0.9) | ✅ Confirmed |
| "Sustainion X37-60 AEM" | `['alkaline ion exchange membrane', 'material spec', 'Sustainion X37-60 bioform dioxide materials']`(conf 0.9) | ✅ Confirmed |
| "10 mm strong-acid cation-exchange resin beads" | `['middle chamber','thickness','10 millimeter']` + `['solid electrolyte','material spec','strong acid cation exchange resin beads']`,粒径 600–800 μm(均 conf 0.9) | ✅ Confirmed |
| "Nafion 117 CEM" | `['anode side membrane', 'material', 'Nafion 117']`,同段确认为"cation exchange membrane (CAM)"(conf 0.9) | ✅ Confirmed |
| "PtRu/C-H23C3 anode" | `['anode electrode', 'preparation method', 'spray coating Pt-Ru-C catalysis onto H23C3 carbon paper']`(conf 0.9) | ✅ Confirmed |

**小结**:文档给出的 R1 结构五要素(阴极催化剂/膜/中间层/CEM/阳极催化剂)在 `R1_1Cell_070` 里逐条都能找到对应三元组,数值和型号完全吻合,是全篇里匹配度最高的结构比对之一。

### 2. 失效诊断比对(R1 失效诊断)

| 文档诊断(confidence) | 视频/知识图谱依据 | 结论 |
|---|---|---|
| 诊断1:"中间固态树脂层欧姆阻抗过大"(high) | `R1_1Cell_070`/`R1_2Test_071` 均只描述装配步骤和进气配置,无任何电压/阻抗相关表述 | ⬜ Not Covered |
| 诊断2:"树脂层水合不足,未形成连续离子通道"(high) | 同上,R1 视频没有 narrator 对水合状态的评价 | ⬜ Not Covered |
| 诊断3:"树脂颗粒床接触不连续"(medium-high) | 同上 | ⬜ Not Covered |

**间接支持**:三条诊断本身在 R1 视频里没有直接证据,但 R2 测试视频(`R2_2Test_005`)明确说"The purpose of pervading is to improve the ionic conductivity of the solid electrolyte and reduce the initial resistance of the middle layer"(conf 0.9)——这句话从侧面印证了文档诊断的核心假设(R1 中间层导电性/阻抗确实是被认定的问题),但属于"下一代设计目的的转述",不是"针对 R1 的直接诊断陈述",因此仍按 Not Covered 记录,不升级为 Partially Confirmed。

### 3. 设计动作/假设比对(R2 设计动作,对照 `R2_1Cell_072/075/076`、`R2_2Test_005`)

| 文档设计动作 | 视频知识图谱 | 结论 |
|---|---|---|
| "R2 = pre-wetted hydrated resin solid electrolyte,最小干预:只改变水合状态" | `R2_2Test_005`: `['middle chamber','contains','solid electrolyte']` + `['solid electrolyte','is being pervaded','before assembly']`(conf 0.3,VLM 无法从静态帧确认"组装前"这个时间点,非真实矛盾) | ✅ Confirmed |
| 假设:"预润湿是否能降低固态树脂层阻抗" | `R2_2Test_005`: `['pervading','purpose','improve ionic conductivity of solid electrolyte']` + `['pervading','purpose','reduce initial resistance of middle layer']`(均 conf 0.75/0.9) | ✅ Confirmed,措辞与文档假设几乎一一对应 |
| 文档结构表隐含"R2 尚无持续水流,是纯粹的一次性预润湿" | `R2_1Cell_075`: `['middle chamber','contains','air-water inlet']` + `['middle chamber','contains','air-water outlet']`,narrator 原话"we will use the air-water to increase the ionic conductivity"(conf 0.9) | 🔴 Discrepancy(见下方重点核实) |

**🔴 需要重点核实的一处出入**:R1-R2 文档把 R2 定义为纯粹的"静态预润湿"(pre-wetted,一次性动作),但 `R2_1Cell_075` 组装视频明确讲到中间腔室已经装有"air-water inlet"和"air-water outlet"两个接口,且 narrator 的表述("we will use the air-water to increase the ionic conductivity of the solid electrolytes")并未限定为一次性动作,读起来更像是主动引入水路而非单纯浸泡。`MASTER_KNOWLEDGE_LOG.md` 的 #4 条也独立观察到这一点,并把它记录为"R2 相对 R1 在设计上新增了'树脂腔室+去离子水流'这一步优化"。而 R2 测试视频(`R2_2Test_005`)里明确说的又是"pervaded before assembly"(强调组装前的一次性动作),两段视频对"R2 到底是一次性预润湿还是已经具备水流能力"存在一定张力。**建议人工核实**:R2 硬件上的 inlet/outlet 是否在 R2 阶段就已经通水(哪怕只是低速/间歇),还是确实只作为硬件预留、直到 R3 才第一次真正启用连续流动——这会影响"R2→R3"这一步改动到底是"从无到有"还是"从静态到持续"。

---

## 二、R2 → R3

### 1. 结构描述比对(R2 结构,对照 `R2-R3` 文档"结构摘要"表)

| 文档描述(R2 列) | 视频知识图谱 | 结论 |
|---|---|---|
| "10 mm pre-wetted strong-acid cation-exchange resin beads" | `R2_1Cell_072/075`: chamber thickness 10mm/10 millimeters,resin beads "strong acid cation exchange resin base/beads",粒径 600–800 micrometer(s) | ✅ Confirmed |
| "水合模式:Static pre-wetting before assembly" | `R2_2Test_005`: "solid electrolyte is being pervaded before assembly" | ✅ Confirmed |
| "流动条件:No continuous middle-chamber flow" | 同上一节的 🔴,`R2_1Cell_075` 显示已有 air-water inlet/outlet | 🔴 Discrepancy(与上节同一处,不重复展开) |

### 2. 失效诊断比对(R2 失效诊断)

| 文档诊断 | 视频依据 | 结论 |
|---|---|---|
| "R2 的预润湿只能改善初始水合状态,不能保证运行过程中持续保持连续水合离子通路"(C3/C1) | `R2_1Cell_072/075/076`、`R2_2Test_005` 均无任何关于 R2 测试后表现、阻抗或失败的评述——R2 唯二的测试/拆解相关内容只有 `R2_2Test_005`,且只讲配置和预润湿目的,不含结果评价 | ⬜ Not Covered |
| "R2 高阻可能来自 bead-bead contact 和 membrane-resin contact"(C5) | 无对应内容;R2 没有拆解视频(拆解阶段素材缺失) | ⬜ Not Covered |

**间接支持**:R3 测试视频的核心动作(持续通水)本身即隐含"R2 的一次性预润湿不够"这一判断,但同上,视频没有一句话直接评价"R2 表现不好",故仍记 Not Covered,不做升级。

### 3. 设计动作/假设比对(R3 设计动作,对照 `R3_2Test_006`)

| 文档设计动作 | 视频知识图谱 | 结论 |
|---|---|---|
| "R3 = 保持树脂体系不变,中间腔引入连续 DI water flow" | `R3_2Test_006`: `['middle chamber','filled with','solid electrolytes']` + `['water','flowing to','middle chamber']`,"There is about 23 sccm water flowing to the middle chamber"(conf 0.9/0.75) | ✅ Confirmed |
| "DI water 是 hydration medium,不是高导电电解质"(这是文档给 Agent 的措辞限定,不是对视频内容的预期) | 视频中 narrator 只说"water"/"air water",没有出现"hydration medium"或"conductivity"这类框架性措辞 | ⬜ Not Covered(此条本身是文档对 Agent 的表述指导,不属于会被 narrator 说出口的内容,标记为未覆盖而非缺陷) |
| 文档强调"R3 是最小因果干预,不直接跳到 1M KOH" | 视频中没有出现对比/展望性表述(R3 视频只描述当前配置) | ⬜ Not Covered |

**⚠️ 数值层面的小出入(非文档-视频出入,记录备查)**:`R3_2Test_006` 中 narrator 说的是"about 23 sccm water",但对应 Echem 文件名里标注的是 `DIwaterFlow10sccm`。这是文件名与视频口播之间的数字不一致(`MASTER_KNOWLEDGE_LOG.md` #7 已记录),与本次"文档 vs 视频"的比对维度无关,但会影响未来如果要把具体流速写入设计文档时的取值来源判断,一并列出供人工复核。

---

## 三、R3 → R4

### 1. 结构描述比对(R3 结构,对照 `R3-R4` 文档"R3 vs R4 design snapshot")

> R3 没有独立的 1.Cell 视频(`R3/1.Cell_same as R2` 文件夹为空,沿用 R2 硬件),因此 R3 的结构需要"R2 装配视频(腔室本体)+ R3 测试视频(新增的连续通水)"两段拼起来验证。

| 文档描述(R3 列) | 视频知识图谱 | 结论 |
|---|---|---|
| "10 mm resin bead chamber with continuous DI water flow" | 腔室本体 10mm 来自 `R2_1Cell_072/075`;连续通水来自 `R3_2Test_006`("23 sccm water flowing to the middle chamber") | ✅ Confirmed(需跨两代视频拼接确认,已在文档层面属合理引用) |

### 2. 失效诊断比对(R3 失效诊断)

| 文档诊断 | 视频依据 | 结论 |
|---|---|---|
| "DI water hydration maintains wetting but does not provide a sufficiently conductive and continuous ionic pathway through the thick resin packed bed"(C2) | `R3_3AfterTest_001` 是 R3 唯一的测试后素材,但因 ASR 复读故障(重复"this is the cathode part, solid state..."),三元组抽取阶段返回 0 条,没有任何可用于诊断比对的内容(见 `MASTER_KNOWLEDGE_LOG.md` #8) | ⬜ Not Covered |
| "The resin bed in R3 can remain tortuous and contact-limited even with flow"(C10) | 同上,无内容 | ⬜ Not Covered |

**特别说明**:R3→R4 是四份文档里"诊断维度"证据最薄弱的一段——不仅缺少电化学数据(这是全篇通病),连拆解视频本身都因 ASR 故障没能提取出任何文本内容。如果未来要为这一步补强证据链,`R3_3AfterTest_001` 原始视频画面(而非 ASR 转录)是唯一可能还原信息的来源。

### 3. 设计动作/假设比对(R4 设计动作,对照 `R4_1Cell_005`、`R4_2Test_006`)

| 文档设计动作 | 视频知识图谱 | 结论 |
|---|---|---|
| "Replace the solid-resin/DI-water-flow middle layer with a circulating 1 M KOH liquid electrolyte" | `R4_1Cell_005`: `['solid electrolyte layer','replaced by','circulating 1 molecule H liquid electrolyte']`(conf 0.9,"1 molecule H" 经词典已知是"1 molar KOH"的 ASR 误听) | ✅ Confirmed |
| "创造连续、高离子强度的离子通路,降低欧姆损耗"(设计目的) | `R4_1Cell_005`: "The purpose is to improve ionic activity in the middle chamber and reduce [resistance]"(conf 0.9,VLM 截断但方向明确);`R4_2Test_006`: "evaluate whether the circulating 1 molar KOH electrolyte can improve the electrochemical performance and solubility of this reactor"(conf 0.75) | ✅ Confirmed |
| "R4 应被当作 resistance-reduction 诊断性设计,同时监测 flooding/crossover 风险" | `R4_2Test_006` 只描述了测试配置和评估目的,没有提到风险监测的具体表述;R4 的拆解视频(`R4_3AfterTest_001/009`)均 0 节点,没有关于水淹/串流风险的观察记录 | 🟡 Partially Confirmed(设计动作本身确认,但"风险监测"这部分文档要求在视频里找不到对应的执行痕迹) |

**一处措辞层面的细节差异**:文档把 R4 明确定位为"取代 R3 的 DI-water-flow 树脂层"(强调 R3 已经尝试过水合强化仍不够),但 `R4_1Cell_005` 视频 narrator 的原话是"the middle **solid electrolyte layer** is replaced by..."——只笼统提到"固态电解质层",并没有专门点出"R3 已经引入过持续通水但仍不足"这一层递进关系,读起来更像是把 R1-R3 当作同一类"固态方案"整体替换,而不是针对 R3 具体失败点的精准回应。判定为 🟡 Partially Confirmed:核心的材料替换动作和设计目的完全一致,但文档强调的"针对 R3 特定不足"这一叙事细节在视频措辞里没有被显性区分出来。

---

## 四、R4 → R5

### 1. 结构描述比对(R4 结构,对照 `R4-R5` 文档"R4 vs R5 design transition")

| 文档描述(R4 列) | 视频知识图谱 | 结论 |
|---|---|---|
| "Middle chamber:10 mm, 1cm×1cm window" | `R4_1Cell_005`: `['middle chamber','thickness','10 mm']` + window "1 by 1 cm" | ✅ Confirmed |
| "Middle electrolyte:Circulating 1 M KOH" | `R4_1Cell_005`: `['liquid electrolyte','is','1 molar KOH']` + "will be continuously circulated through the middle chamber" | ✅ Confirmed |
| "Membrane architecture:AEM Sustainion X37-50 \| 1M KOH \| AEM Sustainion X37-50"(阴阳极两侧对称同型号) | `R4_1Cell_005`: Step4 膜"ion exchange membrane is Sustainion X37-50";Step7 阳极侧膜"membrane material Sustainion X37-50, purchased from Dioxide Materials" | ✅ Confirmed(两侧型号一致,与文档对称结构描述吻合) |

### 2. 失效诊断比对(R4 失效诊断)

| 文档诊断 | 视频依据 | 结论 |
|---|---|---|
| "R4 虽已是连续液态电解质,但 10mm 液层仍可能带来残余欧姆阻抗"(C1/C2) | `R4_2Test_006` 只表达测试目的是"评估循环 1M KOH 电解质能否提升性能",属前瞻性表述,不含任何"确实存在残余阻抗"的结果性陈述;R4 拆解视频均 0 节点 | ⬜ Not Covered |
| "R4 may improve voltage but can introduce flooding/crossover risks" | 无对应内容 | ⬜ Not Covered |

### 3. 设计动作/假设比对(R5 设计动作,对照 `R5_1Cell_016`、`R5_2Test_001`、`R5_2Test_002`、`R5_RecordingFailed_012`)

这是全篇四份文档里**匹配度最高、证据最密集**的一段设计动作比对:

| 文档设计动作 | 视频知识图谱 | 结论 |
|---|---|---|
| "Reduce middle chamber thickness 10mm → 3mm" | `R5_1Cell_016`: `['middle chamber thickness','is reduced to','3 millimeter']`;`R5_RecordingFailed_012`(R5 正式版之前的失败尝试)同样显示 3mm | ✅ Confirmed(两段独立视频互相印证) |
| 假设:"缩短传输距离应降低 PEIS 阻抗、改善 CP 电压" | `R5_1Cell_016`: "The purpose is to shorten the ion transparent distance, reduce the organic[ohmic] resistance from the liquid electro-layer... and to decrease the cell voltage"(conf 0.9);`R5_2Test_001` 几乎逐字重复同一句表述(conf 0.9) | ✅ Confirmed,且被两段独立视频重复陈述,是全篇里唯一一处"假设表述"与文档几乎逐字对应的案例 |
| "Add Hg/HgO reference electrode in the middle chamber, for diagnostic separation of partial-cell vs full-cell resistance" | `R5_1Cell_016`: "we induce this reference electrode into the middle layer. The reference electrode is a mercury oxide electrode"(conf 0.9);`R5_2Test_002` 更进一步**操作化**了这个设计目的:参比电极接中间腔室时测得"R1"(阴极到中间层电阻),接阳极侧时测得"R3"(全电池电阻) | ✅ Confirmed,`R5_2Test_002` 提供的 R1/R3 定义比文档描述得还要具体 |
| "Same AEM/AEM architecture, keep circulating 1M KOH"(最小干预原则) | `R5_1Cell_016`: 阴极侧膜"Sustainion X37-50",阳极侧膜"also Sustainion X37-50";总结句"this reactor keeps the circulating 1 molar KOH liquid electrolytes in the middle chamber but reduces the chamber thickness to 3 millimeter" | ✅ Confirmed,narrator 用近乎文档式的"keeps...but..."句式直接对比了 R4→R5 的变与不变 |
| "Keep CuO cathode, PtRu/C anode 不变" | `R5_1Cell_016`: 阴极三元组写的是"spray coating **carbon dioxide** catalysis onto H23C3 carbon paper" | 🟡 Partially Confirmed(很可能是 ASR 对"copper oxide"的误听,见下) |

**关于"carbon dioxide catalysis"的说明(非真实矛盾,标记原因)**:`R5_1Cell_016` 的三元组把阴极催化剂记录为"carbon dioxide catalysis",字面意思讲不通(二氧化碳是气体,不可能被喷涂在碳纸上做催化剂涂层),而 R1-R4 全部视频里阴极催化剂一致描述为"copper oxide(CuO)catalysis"。结合"copper oxide"和"carbon dioxide"发音相近,这几乎可以确定是本次 ASR 转录的又一个误听变体(类似已记录在 `terminology_dict.json` 里的其他 CuO/Pt-Ru-C 误听案例),而不是 R5 真的更换了催化剂化学成分。判定为 Partially Confirmed 而非 Discrepancy:文档的"催化剂不变"结论大概率是对的,只是这一处视频转录文本本身需要人工核对原始音频、并考虑补充一条词典规则(`carbon dioxide catalysis` → `copper oxide catalysis`)。

---

## 总体总结

### 1. 整体吻合程度

四份设计逻辑文档与视频知识图谱的**结构描述**和**设计动作/假设**这两个维度吻合度非常高——绝大多数条目是 ✅ Confirmed,且不少地方 narrator 的原话在用词上与文档几乎逐字对应(尤其 R4→R5 一段:“shorten the ion transparent distance, reduce...resistance...decrease the cell voltage” 这句话在两段不同视频里被独立重复,和文档假设的措辞高度一致)。这说明设计文档所记录的工程决策链条,和实际装配/测试视频里 narrator 讲述的改动理由,是同一套叙事,没有出现"文档说的是一套、实际做的是另一套"的情况。

### 2. 跨代反复出现的 Not Covered 类型

**"失效诊断"这一个维度,在全部四份文档里都是系统性 Not Covered**,原因高度一致,不是某一代视频质量问题:

- 四份文档的诊断部分本质上都是**基于电化学原理和文献的推理**(欧姆阻抗、水合-电导关系、离子路径长度等),其验证证据链设计上依赖的是 **CP 电压曲线和 PEIS 阻抗谱这类量化电化学数据**——这些数据存放在 `1.Reactor_Agent/Echem/*.mpr` 里,完全不在 video_kg_pipeline 的处理范围内。
- 而且直到 R6 视频里,narrator 才第一次在视频里主动说出完整的失效诊断句子("主要失效模式是阴极水淹");R1-R5 阶段的视频里,narrator 只描述"做了什么"(装配步骤、测试配置、拆解检查项),几乎不评价"为什么上一代表现不好"。
- 因此如果以后想让"诊断维度"也能在视频知识图谱里被直接验证,需要额外把 Echem 电化学数据接入到某个新的处理阶段(目前 stage1-7 都不读取 .mpr 文件),或者在录制装配/拆解视频时明确要求 narrator 口头总结上一代的失效结论(像 R6 那样)。

### 3. 需要重点核实的 Discrepancy

只有**一处**够得上 🔴 Discrepancy 标准,集中出现在 R1→R2 和 R2→R3 两份文档里(其实是同一个技术点在两份文档里各出现一次):

> **文档说 R2 是"纯静态预润湿,无持续水流",但 `R2_1Cell_075` 装配视频显示中间腔室已经装有 air-water inlet 和 outlet,narrator 明确说要用它"来提升离子电导率"。** `MASTER_KNOWLEDGE_LOG.md` 独立分析也提到了同一处观察。这不影响"R2→R3 只是把水合方式升级为持续流动"这个大方向的判断,但具体到"R2 阶段这套 inlet/outlet 是否已经在通水、只是流速/时长不够,还是完全没启用、留到 R3 才第一次真正用上"——这一点文档和视频各执一词,建议直接查看 `R2_1Cell_075` 原始视频画面(而不只是转录文本)或询问实验记录人,确认 R2 测试阶段中间腔室的实际通水状态。

其余标记为 🟡 Partially Confirmed 的条目(R4 设计动作里"R3 已尝试水合仍不足"这一层叙事未被 R4 视频显性区分、R5 阴极催化剂被转录成"carbon dioxide"疑似 ASR 误听)都不构成真正的内容矛盾,已在各自小节里注明具体原因,不需要作为 Discrepancy 重点复核。
