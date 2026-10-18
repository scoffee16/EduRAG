# EduRAG：面向高校实验教学的多课程多模态 RAG 助教平台

## 项目设计文档

---

## 1. 项目背景与定位

当前，通用大模型与联网检索已经能够回答大量公开知识问题，但在高校实验教学场景中仍存在明显短板：

- **私有资料无法访问**：实验指导书、教师 PPT、实验台手册、VHDL/Verilog 代码、仿真波形、学生报告等，均不在公网。
- **多模态理解不足**：电路图、波形图、流程图、表格、代码等，通用 AI 难以精确解析。
- **领域逻辑易错**：微地址序列、控制信号时序、分支条件等，模型容易产生幻觉。
- **引用不可溯源**：无法精确到“第几页、哪张图、哪张表、哪行代码”。
- **无法与实验工具链交互**：不能自动分析波形、编译代码、生成引脚锁定。
- **隐私与成本问题**：实验资料不宜上传公网，且课堂批量使用依赖 API 成本高。

因此，EduRAG 的定位是：

> **面向高校实验教学的私有、多模态、可验证、可集成工具链的领域专用 RAG + Agent 平台。**

它不局限于计算机组成原理，而是通过**课程包机制**支持操作系统、编译原理、计算机网络、数字逻辑、数据结构、数据库等多门专业课。每门课只需配置解析规则、知识图谱、工具链，即可快速构建专属实验助教。

---

## 2. 项目目标

### 2.1 总体目标
构建一个可扩展的多课程多模态 RAG 平台，为高校实验教学提供：

- 私有资料的安全接入与多模态解析；
- 精确可溯源的问答与推理；
- 领域知识图谱驱动的确定性推理；
- Agent 多步工作流与工具调用；
- 与实验工具链（仿真器、编译器、波形分析器）的集成；
- 本地/校内私有化部署。

### 2.2 具体目标
- 支持至少 5 门专业课的课程包快速接入；
- 支持文本、表格、图像、代码、波形五类模态；
- 问答引用精确到页/图/表/行；
- 典型实验任务（如微程序生成、波形检查）自动化完成；
- 提供 RESTful API 与 Web 界面；
- 支持离线运行，数据不出校内。

---

## 3. 系统总体架构

EduRAG 采用分层模块化架构，自上而下分为：

```
┌─────────────────────────────────────────────────────────┐
│                      前端交互层                          │
│   Web 聊天 / 文档上传 / 引用展示 / 波形查看 / 任务面板    │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    API 网关层（FastAPI）                  │
│   /upload  /query  /agent  /tools  /courses  /health     │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    Agent 编排层                           │
│   问题分类 → 检索规划 → 工具调用 → 结果融合 → 答案生成    │
│   参考：SuperAGI、LangGraph、AutoGen                     │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    检索与推理层                           │
│   检索分发器：文本/表格/图像/代码/波形 → 混合检索         │
│   知识图谱推理：实体关系、规则引擎、图遍历                │
│   参考：DocsGPT 检索分发器、R2R 混合搜索                  │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    索引与存储层                           │
│   向量库：Qdrant / FAISS                                 │
│   图数据库：Neo4j / NetworkX                             │
│   关系库：PostgreSQL                                     │
│   对象存储：MinIO                                        │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    多模态解析层                           │
│   PDF/PPT → MinerU / Unstructured                        │
│   图像 → CLIP / Qwen-VL / ColPali                        │
│   表格 → Camelot / 表格结构化                            │
│   代码 → Tree-sitter / AST                               │
│   波形 → 波形解析器 + 图像识别                           │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                    课程包管理层                           │
│   课程配置 / 解析规则 / 知识图谱Schema / 工具链定义       │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 多课程适配机制：课程包（Course Pack）

每门课定义为一个**课程包**，包含以下内容：

```yaml
course_pack:
  name: "计算机组成原理"
  code: "CS-COMP-ORG"
  description: "微程序控制器、模型机、CPU设计"
  
  parsers:
    - type: pdf
      handler: mineru
    - type: pptx
      handler: unstructured
    - type: image
      handler: qwen-vl
    - type: vhdl
      handler: tree-sitter-vhdl
    - type: waveform
      handler: wave-analyzer

  knowledge_graph:
    schema: "comp_org_schema.json"
    entities:
      - Instruction
      - MicroAddress
      - ControlSignal
      - Register
      - ALU
      - BranchCondition
    relations:
      - instruction_has_microsequence
      - microaddress_emits_signal
      - branch_condition_determines_next
      - signal_controls_component

  tools:
    - name: "vhdl_simulator"
      type: "external"
      endpoint: "http://localhost:8081/simulate"
    - name: "waveform_checker"
      type: "python"
      module: "tools.waveform_checker"
    - name: "microprogram_generator"
      type: "python"
      module: "tools.microprogram_gen"

  retrieval_config:
    text_weight: 0.4
    table_weight: 0.2
    image_weight: 0.2
    code_weight: 0.2
    rerank: true
    hybrid_search: true
```

新增课程只需编写课程包，无需修改核心代码。平台自动加载解析器、知识图谱、工具链和检索配置。

---

## 5. 多模态文档处理流水线

### 5.1 文档解析
- **PDF/PPT**：使用 MinerU 提取文本、表格、图像、公式，保留版面结构。
- **Word（.docx）**：使用 python-docx 提取段落与表格文本，按 Heading 样式切块，表格转为行列文本。
- **图像**：使用 Qwen-VL 或 CLIP 生成多模态嵌入，识别电路图、流程图、波形图。
- **表格**：结构化解析为 JSON，并生成自然语言摘要。
- **代码**：使用 Tree-sitter 解析 AST，提取函数、模块、信号、端口。
- **波形**：解析 VCD/CSV 或截图，提取信号时序、微地址序列、控制信号变化。

### 5.2 分块与嵌入
- 文本按语义分块，表格按行/列分块，图像按区域分块，代码按函数/模块分块。
- 每块生成：
  - 文本嵌入（BGE / text-embedding-3）；
  - 多模态嵌入（CLIP / ColPali）；
  - 元数据：来源、页码、坐标、课程包、实体链接。

### 5.3 知识图谱构建
- 实体抽取：指令、微地址、控制信号、寄存器、ALU、分支条件。
- 关系抽取：`指令 → 微地址序列`、`微地址 → 控制信号`、`分支条件 → 下一条微地址`。
- 图存储：Neo4j，支持图遍历和规则推理。

---

## 6. 检索与推理引擎

### 6.1 检索分发器
参考 DocsGPT 的 Retriever Dispatcher：
- 问题分类：概念、流程、波形、代码、计算。
- 按类型路由到不同检索器：
  - 文本检索器：BM25 + 向量；
  - 表格检索器：结构化查询；
  - 图像检索器：多模态相似度；
  - 代码检索器：AST 匹配；
  - 波形检索器：时序模式匹配。
- 混合检索：倒数排名融合（RRF）合并结果。
- 重排序：Cross-Encoder 或 LLM 重排。

### 6.2 知识图谱推理
- 对于“ADD 指令的微地址序列是什么？”这类问题，直接在图谱中查询 `instruction_has_microsequence`。
- 对于“`SE[6..1]` 什么时候有效？”查询 `microaddress_emits_signal` 和 `branch_condition_determines_next`。
- 规则引擎：如“若 `T4=1` 且 `P[1]=1` 且 `I[7..2]=000100`，则 `SE=111110`，下地址 `11`”。

### 6.3 可验证引用
每个答案附带：
- 文档名、页码、区域坐标；
- 表格行号、代码行号；
- 图谱路径：实体 → 关系 → 实体；
- 工具调用记录：仿真输出、波形分析结果。

---

## 7. Agent 编排与工具集成

### 7.1 Agent 工作流
1. **问题理解**：分类问题，提取实体和意图。
2. **检索规划**：决定使用哪些检索器和工具。
3. **多步执行**：
   - 检索文本/表格/图像/代码；
   - 查询知识图谱；
   - 调用工具（VHDL 仿真、波形分析、微程序生成）。
4. **结果融合**：合并多源信息，解决冲突。
5. **答案生成**：生成自然语言答案，附引用和工具输出。
6. **自我检查**：验证答案与检索结果一致性。

### 7.2 工具链示例
| 工具         | 功能                                      | 集成方式          |
| ------------ | ----------------------------------------- | ----------------- |
| VHDL 仿真器  | 编译并仿真 VHDL 代码                      | REST API / 子进程 |
| 波形分析器   | 解析 VCD/CSV，检查 `uaddr`、`M`、`I`、`P` | Python 模块       |
| 微程序生成器 | 输入指令，输出微地址序列和控制信号表      | Python 模块       |
| 引脚锁定助手 | 根据实验台型号生成引脚分配                | 规则引擎 + 数据库 |
| 代码检查器   | 检查 VHDL 是否实现指定控制信号            | AST + 规则        |

### 7.3 Agent 框架选型
- **LangGraph**：状态机式工作流，适合多步推理。
- **AutoGen**：多 Agent 协作，适合复杂任务分解。
- **自研轻量 Agent**：基于 FastAPI + 状态机，适合课程项目。

---

## 8. 技术选型

| 模块       | 推荐技术                          |
| ---------- | --------------------------------- |
| 后端框架   | Python + FastAPI                  |
| RAG 框架   | LangChain / LlamaIndex            |
| 向量库     | Qdrant / FAISS                    |
| 图数据库   | Neo4j / NetworkX                  |
| 关系库     | PostgreSQL                        |
| 对象存储   | MinIO                             |
| 文档解析   | MinerU + Unstructured             |
| 多模态嵌入 | CLIP / Qwen-VL / ColPali          |
| 代码解析   | Tree-sitter                       |
| 本地 LLM   | Ollama + Qwen2.5 / Llama 3        |
| 云端 LLM   | OpenAI GPT-4o / Claude / 通义千问 |
| 前端       | React + Tailwind + Vite           |
| 部署       | Docker Compose                    |
| 监控       | Prometheus + Grafana              |

---

## 9. 数据模型（核心表）

### 9.1 课程包表 `course_packs`
| 字段        | 类型        | 说明                       |
| ----------- | ----------- | -------------------------- |
| id          | UUID        | 主键                       |
| name        | VARCHAR     | 课程名                     |
| code        | VARCHAR     | 课程代码（唯一）           |
| description | TEXT        | 课程描述（可空，回退配置） |
| config      | JSONB       | 课程包配置                 |
| created_at  | TIMESTAMP   | 创建时间                   |
| updated_at  | TIMESTAMPTZ | 最近同步/更新时间          |

### 9.2 文档表 `documents`
| 字段         | 类型    | 说明                                  |
| ------------ | ------- | ------------------------------------- |
| id           | UUID    | 主键                                  |
| course_id    | UUID    | 外键                                  |
| filename     | VARCHAR | 文件名                                |
| file_type    | VARCHAR | pdf/pptx/docx/vhdl/vcd                |
| storage_path | VARCHAR | MinIO 路径                            |
| status       | VARCHAR | processing/indexed/failed（默认 indexed） |
| metadata     | JSONB   | 元数据（进度、页数、块数、created_at） |

### 9.3 块表 `chunks`
| 字段        | 类型    | 说明                       |
| ----------- | ------- | -------------------------- |
| id          | UUID    | 主键                       |
| document_id | UUID    | 外键                       |
| content     | TEXT    | 文本内容                   |
| modality    | VARCHAR | text/table/image/code/wave |
| embedding   | VECTOR  | 向量                       |
| metadata    | JSONB   | 页码、坐标、行号           |

### 9.4 实体表 `entities`
| 字段       | 类型    | 说明                         |
| ---------- | ------- | ---------------------------- |
| id         | UUID    | 主键                         |
| course_id  | UUID    | 外键                         |
| type       | VARCHAR | Instruction/MicroAddress/... |
| name       | VARCHAR | 实体名                       |
| properties | JSONB   | 属性                         |

### 9.5 关系表 `relations`
| 字段       | 类型    | 说明     |
| ---------- | ------- | -------- |
| id         | UUID    | 主键     |
| source_id  | UUID    | 源实体   |
| target_id  | UUID    | 目标实体 |
| type       | VARCHAR | 关系类型 |
| properties | JSONB   | 属性     |

### 9.6 工具调用表 `tool_calls`
| 字段       | 类型      | 说明   |
| ---------- | --------- | ------ |
| id         | UUID      | 主键   |
| session_id | UUID      | 会话   |
| tool_name  | VARCHAR   | 工具名 |
| input      | JSONB     | 输入   |
| output     | JSONB     | 输出   |
| created_at | TIMESTAMP | 时间   |

---

## 10. API 设计

| 方法 | 路径                        | 功能           |
| ---- | --------------------------- | -------------- |
| POST | `/api/v1/upload`            | 上传文档       |
| POST | `/api/v1/query`             | 普通 RAG 问答  |
| POST | `/api/v1/agent`             | Agent 多步问答 |
| POST | `/api/v1/tools/{tool_name}` | 调用工具       |
| GET  | `/api/v1/courses`           | 课程列表       |
| POST | `/api/v1/courses`           | 创建课程包     |
| GET  | `/api/v1/documents/{id}`    | 文档详情       |
| GET  | `/api/v1/health`            | 健康检查       |

---

## 11. 实现路线图

### 第一阶段：MVP（1-2 周）
- 支持 PDF/PPT/Word 文本解析；
- 向量检索 + 基础问答；
- 单一课程（计算机组成原理）；
- Web 界面 + API。

### 第二阶段：多模态（2-4 周）
- 加入表格、图像、代码解析；
- 多模态嵌入；
- 引用精确到页/图/表；
- 波形图识别。

### 第三阶段：知识图谱 + Agent（4-6 周）
- 构建领域知识图谱；
- 检索分发器；
- Agent 工作流；
- 工具集成（VHDL 仿真、波形分析）。

### 第四阶段：多课程平台（6-8 周）
- 课程包机制；
- 支持 3-5 门课程；
- 私有化部署；
- 性能优化与评估。

---

## 12. 创新点与优势

| 维度       | 通用 AI 联网检索 | EduRAG                   |
| ---------- | ---------------- | ------------------------ |
| 资料范围   | 公开网页         | 私有实验资料 + 公开资料  |
| 多模态     | 文本为主         | 文本+表格+图像+代码+波形 |
| 引用       | 模糊             | 精确到页/图/表/行        |
| 领域逻辑   | 靠模型猜         | 知识图谱 + 规则推理      |
| 工具调用   | 基本没有         | 编译器、仿真器、波形分析 |
| 隐私       | 上传公网         | 本地/校内私有部署        |
| 成本       | 依赖 API         | 可离线，成本可控         |
| 教学适配   | 通用回答         | 符合课程要求和实验步骤   |
| 多课程扩展 | 无               | 课程包机制，快速接入     |

---

## 13. 总结

EduRAG 是一个面向高校实验教学的多课程多模态 RAG + Agent 平台。  
它不局限于计算机组成原理，而是通过课程包机制，支持操作系统、编译原理、计算机网络、数字逻辑等多门专业课。  
其核心优势在于：私有资料、多模态理解、可验证引用、知识图谱推理、Agent 工具链集成、离线部署。  
相比通用 AI 联网检索，EduRAG 更懂实验、更懂课程、更懂工具，是实验教学的“最后一公里”解决方案。

---

## 目录结构

当前仓库（ED-00 集成结果）的主要目录如下：

```text
EduRAG/
├── .github/workflows/ci.yml
├── configs/
│   ├── app.yaml
│   └── course_packs/comp_org.yaml
├── docker/
│   ├── .dockerignore
│   ├── Dockerfile
│   └── postgres/init.sql
├── docs/development.md
├── scripts/
│   ├── dev.ps1
│   └── dev.sh
├── src/edurage/
│   ├── api/v1/endpoints/health.py
│   ├── api/v1/router.py
│   ├── core/config.py
│   ├── core/logging.py
│   ├── courses/loader.py
│   ├── courses/schema.py
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_course_pack.py
│   ├── test_env_contract.py
│   ├── test_health.py
│   └── test_smoke_import.py
├── .env.example
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 开发环境搭建

要求 Python 3.11+；运行容器工作流时需要 Docker Desktop/Compose。

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

`.env.example` 中冻结的 39 个 `EDURAGE_*` 键是运行契约，不应改名或删除；生产环境必须替换其中的密钥占位值。开发与验收命令统一使用 `python -m pip`、`python -m pytest`、`python -m ruff`，避免 PATH 指向不同解释器。

## 本地启动 / Docker Compose 启动

本机启动：

```powershell
python -m uvicorn edurage.main:app --reload --host 127.0.0.1 --port 8000
curl.exe http://127.0.0.1:8000/api/v1/health
```

健康检查返回的冻结契约是：

```json
{"status":"ok","service":"edurage","version":"0.0.1"}
```

Docker Compose 启动基础设施与 API：

```powershell
docker compose config
docker compose up -d postgres qdrant minio
docker compose up -d --build api
docker compose ps
docker compose logs --no-color --tail 30 postgres qdrant minio api
docker compose down
```

API 依赖 healthy 的 PostgreSQL 和 Qdrant；MinIO 提供文档对象存储。默认端口为 API `8000`、PostgreSQL `5432`、Qdrant `6333/6334`、MinIO `9000/9001`。

> MVP 阶段使用云端 LLM，与 §2.2 离线目标存在阶段性差异。

## ED-00 验收结果

验收日期：2026-09-22。集成分支：`codex/ed-00-05-integration`。总体结果：**PASS**。

| 验收项 | 命令/检查 | 结果 |
| --- | --- | --- |
| 开发依赖安装 | `python -m pip install -e ".[dev]"` | 通过，edurage 0.0.1 可编辑安装成功 |
| 静态检查 | `python -m ruff check .` | 通过，All checks passed |
| 自动化测试 | `python -m pytest -q` | 通过，8 passed；1 条 Starlette/httpx 第三方弃用警告 |
| Compose 配置 | `docker compose config` | 通过，服务、端口、健康检查和卷配置解析成功 |
| 真实进程健康检查 | `python -m uvicorn edurage.main:app` 后请求 `/api/v1/health` | 通过，返回冻结契约 JSON |
| 基础设施容器 | `docker compose up -d postgres qdrant minio` | 通过，三容器均为 healthy |
| API 容器（加分项） | `docker compose up -d --build api` | 通过，API 容器 healthy 且健康检查契约通过 |

容器日志摘要：PostgreSQL 完成扩展、schema、表初始化并通过 `pg_isready`；Qdrant 1.12.5 启动 REST 6333 与 gRPC 6334；MinIO 启动对象存储 API 9000 与控制台 9001；API 容器使用 uvicorn 启动并响应健康检查。

## ED-01 MVP 验收标准（上传 PDF → 提问 → 引用到页 → pytest 全绿）

ED-01 必须满足以下端到端链路，且不得改变 ED-00 冻结契约：

1. **上传 PDF**：调用 `POST /api/v1/upload` 上传一份计算机组成原理 PDF，使用课程包 `CS-COMP-ORG`；响应必须返回可追踪的 `document_id`，并在存储中保留源文件与页面元数据。
2. **提问**：调用 `POST /api/v1/query`，提出答案明确存在于该 PDF 中的问题；请求指定 `course_pack` 和可选 `document_ids`，响应必须在可接受时限内返回答案。
3. **引用到页**：回答必须包含非空的结构化引用，每条引用至少包含 `document_id`、文件名、页码、片段文本/位置和相关性分数；页码必须与 PDF 实际页一致，不能只返回整篇文档级引用。
4. **全量回归**：`python -m pytest -q` 必须全绿；至少覆盖上传、查询、页级引用和错误路径，并保留 ED-00 的健康检查、环境契约、课程包契约回归测试。
5. **验收命令**：

```powershell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
docker compose config
```

ED-01 可使用云端 LLM 完成 MVP 链路，但必须显式配置密钥并遵守数据上传策略；将模型切换为本地/离线推理属于与 §2.2 离线目标对齐的后续工作。

---

## ED-01 MVP 使用说明

ED-01 当前提供 PDF 上传、按页解析、向量检索和带页码引用的问答 API。服务启动后，健康检查地址为 `GET /api/v1/health`。

### DeepSeek / DashScope 配置

复制 `.env.example` 为 `.env`，填入真实密钥；`.env` 不得提交到 Git：

```dotenv
EDURAGE_LLM_PROVIDER=deepseek
EDURAGE_LLM_BASE_URL=https://api.deepseek.com
EDURAGE_LLM_MODEL=deepseek-chat
EDURAGE_LLM_API_KEY=<DEEPSEEK_API_KEY>

EDURAGE_EMBEDDING_PROVIDER=dashscope
EDURAGE_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EDURAGE_EMBEDDING_MODEL=text-embedding-v3
EDURAGE_EMBEDDING_API_KEY=<DASHSCOPE_API_KEY>
```

`deepseek-chat` 和 `text-embedding-v3` 是当前配置契约；不要替换为 `gpt-4o-mini` 或 `qwen-plus`。上传云端前请确认资料策略，默认 `EDURAGE_ALLOW_CLOUD_UPLOAD=false`。

### 上传 PDF

启用上传后，使用课程包代码 `CS-COMP-ORG`：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/upload `
  -F "file=@sample.pdf;type=application/pdf" `
  -F "course_code=CS-COMP-ORG"
```

响应包含 `document_id`、页数、分块数和索引状态：

```json
{
  "document_id": "00000000-0000-0000-0000-000000000000",
  "filename": "sample.pdf",
  "pages": 3,
  "chunks": 3,
  "course_code": "CS-COMP-ORG",
  "status": "indexed"
}
```

### 提问并查看页码引用

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/query `
  -H "Content-Type: application/json" `
  -d '{ "question": "ADD 指令的微地址序列是什么？", "course_code": "CS-COMP-ORG", "top_k": 5 }'
```

响应的 `citations` 数组包含 `document_id`、`filename`、`page`、`snippet`、`score` 和 `modality`；ED-01 验收要求该问题的离线样例响应包含 `page: 2`。

### ED-01-05 验收结果

验收日期：2026-10-10。分支：`codex/ed-01-05-integration`。

| 验收项 | 结果 |
| --- | --- |
| `python -m ruff check .` | 通过，All checks passed |
| `docker compose config` | 通过 |
| `$env:TEMP='.tmp'; $env:TMP='.tmp'; $env:TMPDIR='.tmp'; python -m pytest -q --basetemp .pytest-tmp` | 通过，36 passed, 1 skipped |
| 离线 PDF 上传 → 查询 → `citations` 含 `page=2` | 通过，`tests/e2e/test_e2e_sample_pdf.py` |
| Docker PostgreSQL/Qdrant/MinIO | partial：Docker Desktop Linux engine 不可用，named pipe `dockerDesktopLinuxEngine` 不存在 |
| `scripts/init_db.py` / `scripts/init_qdrant.py` | 未执行：受上述 Docker 阻塞，未伪造结果 |
| Live DeepSeek/DashScope 冒烟 | 未执行：本次验收未启用 `EDURAGE_LIVE_API_TESTS=1`，不打印或暴露 Key |

容器验收恢复后，执行：

```powershell
docker compose up -d postgres qdrant minio
python scripts/init_db.py
python scripts/init_qdrant.py
docker compose ps
```

**文档版本**：v1.1（ED-00 集成）
**日期**：2026-10-10
**作者**：EduRAG 项目组

## ED-02 文档生命周期与 PDF/PPTX 检索

ED-02 在 ED-01 的 PDF RAG MVP 上增加文档生命周期管理、PPTX 文本摄取和跨格式引用：

- 支持 `.pdf` 和 `.pptx` 按页/slide 解析、分块、嵌入和检索；
- PDF 引用中的 `page` 表示 PDF 页码，PPTX 引用中的 `page` 表示 slide 编号；
- Qdrant payload 保留 `document_id`、`filename`、`file_type`、`page` 和 `chunk_index`；
- `document_id` 可作为查询过滤条件，未指定时继续按 `course_code` 检索；
- 当前不解析图片、音频、动画和嵌入对象。

### ED-02 API

`POST /api/v1/upload` 同时支持 PDF 和 PPTX，服务根据文件扩展名选择解析器：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/upload `
  -F "file=@sample.pdf;type=application/pdf" `
  -F "course_code=CS-COMP-ORG"

curl.exe -X POST http://127.0.0.1:8000/api/v1/upload `
  -F "file=@sample.pptx;type=application/vnd.openxmlformats-officedocument.presentationml.presentation" `
  -F "course_code=CS-COMP-ORG"
```

查询支持可选的 `document_id`：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/query `
  -H "Content-Type: application/json" `
  -d '{ "question": "ADD 指令的微地址序列是什么？", "course_code": "CS-COMP-ORG", "document_id": "<DOCUMENT_ID>", "top_k": 5 }'
```

文档列表支持按课程过滤，删除接口只删除指定文档及其对象、向量和分块记录：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/documents?course_code=CS-COMP-ORG"
curl.exe -X DELETE "http://127.0.0.1:8000/api/v1/documents/<DOCUMENT_ID>"
```

删除前应确认 `document_id`；不存在的文档返回 `404`，删除不会影响其它文档。真实资料、业务数据和包含敏感信息的文件不得提交 Git；云端 DeepSeek/DashScope Key 不得写入日志。

### ED-02 验收结果

验收日期：2026-10-13。集成分支：`codex/ed-02-04-integration`。总体结果：**PASS（离线集成验收）**。

| 验收项 | 结果 |
| --- | --- |
| 三个 ED-02 分支按顺序集成 | 通过，无冲突 |
| 开发依赖安装 | 通过，`python -m pip install -e ".[dev]"` |
| 全量自动化测试 | 通过，`63 passed` |
| Ruff / Compose / diff 检查 | 通过 |
| 三页 PDF dry-run | 通过，页码 `[1,2,3]`、chunk 索引连续 |
| 三 slide PPTX dry-run | 通过，slide `[1,2,3]`、chunk 索引连续 |
| 文档列表、删除和 `document_id` 过滤 | 通过，离线测试覆盖 |
| Docker、真实 DeepSeek/DashScope 调用 | 未执行；未伪造结果 |

## ED-03 课程接口、异步上传进度与 Word 支持

ED-03 在 ED-02 基础上补齐课程发现、上传可观测性和 Word 文档支持：

- **课程列表**：`GET /api/v1/courses` 返回课程名、描述、文档数/块数，供前端下拉选择；API 启动时把 `configs/course_packs/*.yaml` 幂等同步进 `course_packs` 表（name/description/config/updated_at），用新课程代码上传文档时自动创建课程行。
- **异步上传**：`POST /api/v1/upload` 立即返回 `202` 与 `document_id`，解析/分块/embedding/写索引在后台执行；`GET /api/v1/documents/{document_id}` 返回 `status` 与 `progress`（parse/chunk/embed/store），失败时返回 `error_code`。
- **Word**：支持 `.docx`（python-docx 解析段落+表格，按 Heading 切块，`page` 表示章节块序号）；`.doc` 需另存为 `.docx`。
- **启动脚本**：`start_edurage.bat` 在 API 健康检查通过后自动打开「API 日志（后端 / LLM 请求）」与「基础设施日志」窗口；也可双击 `scripts/logs.bat` 随时查看容器日志。
- **前端**：课程下拉实时切换文档列表；回答使用 Markdown + KaTeX 渲染；上传显示阶段进度条；布局调整为问答居中、上传/文档列表右侧 sticky。

### ED-03 API 示例

```powershell
# 课程列表
curl.exe http://127.0.0.1:8000/api/v1/courses

# 上传（异步，返回 202）
curl.exe -X POST http://127.0.0.1:8000/api/v1/upload `
  -F "file=@sample.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" `
  -F "course_code=CS-COMP-ORG"

# 轮询进度
curl.exe http://127.0.0.1:8000/api/v1/documents/<DOCUMENT_ID>
```

数据库迁移：新增列通过 `scripts/init_db.py`（`Base.metadata.create_all()` 之后执行幂等 `ADD COLUMN` 迁移）与 API 启动 lifespan（best-effort）完成，兼容已有数据库，无需手写 SQL。

### ED-03 验收结果

全量回归（Windows 11 / Python 3.13 / Node 24 / Docker Desktop）：

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 后端静态检查 | `python -m ruff check .` | All checks passed |
| 后端测试 | `python -m pytest -q` | 222 passed, 1 warning（第三方 pandas/numexpr 提示，与项目无关） |
| 前端测试 | `cd frontend; npm run test` | 17 passed（`src/App.test.tsx`） |
| 前端构建 | `cd frontend; npm run build` | 通过（`tsc -b && vite build`，gzip 188 kB） |
| 容器健康 | `docker compose ps` | api/postgres/qdrant/minio 均 healthy |
| 健康检查契约 | `GET /api/v1/health` | `{"status":"ok","service":"edurage","version":"0.0.1"}`（未变） |

真实容器端到端（重建 `edurage-api:local` 后经 `http://127.0.0.1:8000` 验证）：

- `GET /api/v1/courses` 返回 6 字段，含 `document_count`/`chunk_count` 聚合与 `updated_at`；启动日志显示 `course pack CS-COMP-ORG unchanged`（容器内已包含 `configs/`）。
- PDF、PPTX、DOCX 三种样例上传均返回 `202 {document_id,filename,course_code,status:"processing"}`，轮询 `GET /api/v1/documents/{id}` 全部变为 `indexed`（3/3/2 chunks，`progress:null`、`error_code:null`）。
- 中文提问返回 Markdown 列表 + `$$ ... $$` LaTeX 的答案与带 page 的引用（问题 3 的格式约定生效）。
- 负向契约：`.doc` → 400 `unsupported_file_type`（提示另存 `.docx`）；伪造 PDF 魔数 → 400 `invalid_upload`；不存在的 document_id → 404 `not_found`（统一错误 envelope + `request_id`）。
- `course_packs.description/updated_at` 与 `documents.status` 迁移在既有 dev 数据库上幂等执行，未丢数据（7 篇文档 / 405 chunks 不变）。
- `start_edurage.bat` 在 `:health_ok` 之后打开「EduRAG API 日志（后端 / LLM 请求）」与「EduRAG 基础设施日志（Postgres / Qdrant / MinIO）」两个窗口（已用等价命令验证 `docker compose logs -f` 子进程可正常启动），文件保持 GBK + CRLF。
