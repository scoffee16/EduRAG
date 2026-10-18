# EduRAG 现存问题与解决方案

- 版本：v1（2026-10-18）
- 依据：当前仓库状态（ED-00 ~ ED-04 已交付）+ 实际使用中反馈的 6 个问题
- 说明：本文只给「背景 / 原因 / 方案 / 验收」，实施时按第 7 节顺序执行

## 0. 背景与现状

- 技术栈：FastAPI + Qdrant + PostgreSQL(pgvector) + MinIO；前端 React 18 + Vite 6 + TypeScript；`docker compose` 四容器（api/postgres/qdrant/minio）已全部 healthy。
- 已跑通链路：登录后上传 PDF/PPTX → 解析分块 → DashScope embedding → 检索 → DeepSeek 回答 + 页码引用；真实 API Key 已在容器内验证可用。
- 一键启动脚本 `start_edurage.bat` 已修复（GBK+CRLF、`chcp 936`、`localhost:5173` 等待就绪），可正常拉起后端与前端。
- 课程包机制（`configs/course_packs/*.yaml`）在设计上已存在，但运行时尚未真正接入；前端是 ED 系列验收用的最小 UI，因此出现以下 6 类问题。

| # | 问题 | 一句话原因 | 优先级 |
|---|------|-----------|--------|
| 1 | 课程与文档关联弱、无课程下拉、切换课程列表不刷新 | 课程代码是前端自由文本，后端无课程列表接口，课程配置没同步进数据库 | P0 |
| 2 | 页面空白多、问答不在主位、文档区位置不符合预期 | 现有布局为「左栏上传+列表、右栏问答」，首屏还有大装饰区 | P0 |
| 3 | 回答里的公式/特殊字符原样显示 | 前端用纯文本渲染 `answer`，没有 Markdown/LaTeX 渲染；Prompt 也未约定输出格式 | P0 |
| 4 | 页面不够精美 | 没有设计 token 与组件化规范，样式为单文件压缩式堆叠 | P1 |
| 5 | 上传文档像卡死，不知道在解析还是崩溃 | 上传是同步长请求、无进度回传；后端日志只在容器里，启动脚本不显示 | P0（日志窗）/ P1（进度） |
| 6 | 只支持 PDF/PPTX，想要 Word | 上传白名单、解析分发、前端文案、依赖都只覆盖 pdf/pptx | P1 |

## 1. 课程与文档关联弱 / 需要课程下拉与实时切换

### 背景与现象

- 上传和问答都要求手填「课程代码」，默认写死 `CS-COMP-ORG`；填错或换一个代码，文档列表就空。
- 切换课程时，文档列表不跟着变（要再点一次「查询」）；用户感觉「文档和课程关联性不强」。

### 原因（代码定位）

- 前端课程代码是普通输入框：`frontend/src/App.tsx:165`，默认值硬编码在 `App.tsx:11`（`DEFAULT_COURSE = 'CS-COMP-ORG'`）。
- `onCourseChange`（`App.tsx:80-84`）只更新 state、清空选中，**没有重新请求文档列表**；列表只在初次加载（`App.tsx:66-78`）、点「查询」（`App.tsx:182`）、上传成功后（`App.tsx:97`）刷新。
- 后端按课程代码**精确字符串**过滤：`src/edurage/api/v1/endpoints/documents.py:15-22` → `src/edurage/db/repository.py:88-93`；检索侧同样按精确值过滤（`src/edurage/rag/hybrid_retriever.py:69-73`、`retriever.py:155-159`）。
- 后端没有课程列表接口：`src/edurage/api/v1/router.py:7-13` 只挂了 health/upload/query/documents；README 规划了 `GET /api/v1/courses`（`README.md:332`）但未实现。
- 课程主数据没进运行时：`configs/course_packs/comp_org.yaml:1-5` 定义了课程名/代码/描述，但 `load_course_pack`（`src/edurage/courses/loader.py:30`）只在测试里用；数据库里的 `course_packs` 行是上传时用表单字符串隐式创建的，且 `name = code`、`config = {}`（`src/edurage/ingest/indexer.py:324-336`），课程名/简介/课程包配置与库中数据脱节。

### 解决方案

**后端（新增课程接口 + 配置同步）**

1. 新增 `GET /api/v1/courses`，返回课程列表（含文档数/分块数）：
   ```json
   [{"code":"CS-COMP-ORG","name":"计算机组成原理","description":"微程序控制器、模型机、CPU设计",
     "document_count":3,"chunk_count":42,"updated_at":"2026-10-18T09:00:00Z"}]
   ```
   数据源：`course_packs` 表 join `documents` 聚合；`description` 缺失时回退到 `config` JSONB。
2. 启动时把 `configs/course_packs/*.yaml` 幂等同步进库（以 `code` 为唯一键 upsert：写 `name/description/config`）。实现位置建议 `src/edurage/courses/sync.py`，在 `src/edurage/main.py:15-33` 的 lifespan 中调用，或由 `scripts/init_db.py` 调用。
3. 上传时凡未登录的课程代码自动建课程行（保持现有行为），并把课程代码统一规范化：`course_code.strip().upper()`（`upload.py:50`、`schemas.py:17-27` 处统一处理）。

**数据库（可选最小改动 / 推荐完整改动）**

- 最小方案：不加列，`description` 存进 `course_packs.config` JSONB，课程名沿用 `name`。
- 推荐方案：`course_packs` 增加 `description TEXT NULL`、`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`；`documents` 增加 `status VARCHAR(32) NOT NULL DEFAULT 'indexed'`（配合第 5 节进度查询）。
- 迁移注意：当前建表是 `scripts/init_db.py:7-9` 的 `Base.metadata.create_all()`，**不会给已存在表加列**。要么引入 Alembic（推荐），要么在 `docker/postgres/init.sql` / 手工执行 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` 一次。

**前端（下拉 + 实时切换）**

1. `api.ts` 增加 `getCourses()`。
2. 课程输入框（`App.tsx:165`）改为 `<select>`：选项来自课程列表，显示「课程名（代码）· N 篇文档」；保留「手动新建课程」入口用于新课程。
3. 切换课程时**立即** `loadDocuments(code)`，并清空 `selectedDocument` 与上一次回答（替换 `App.tsx:80-84`）。
4. 上传成功后刷新课程列表与文档列表；文档行同时显示课程名与代码。

### 验收

- 下拉中能看到全部已有课程及文档数；切换课程后文档列表 1s 内实时变化。
- 用一个新课程代码上传文档后，该课程立刻出现在下拉中，且问答按该课程检索有结果。
- 传错课程代码时不再出现「列表为空但不知道原因」的情况（下拉从源头避免手填错误）。

## 2. 页面布局重排：问答居中为主，上传/文档列表放到右侧

### 背景与现象

- 当前布局：左栏窄、右栏宽；左栏堆「添加课程文档 + 课程文档」，问答在右栏。
- 首屏有大标题 hero 区、卡片间距大，视觉上空白多；用户要求「提问模块居中为主，添加文档与文档列表上下放置、统一放到提问区右侧」。

### 原因（代码定位）

- 外层栅格：`frontend/src/styles.css` 中 `.grid-layout{display:grid;grid-template-columns:minmax(330px,420px) minmax(0,1fr);...}` —— 第一列（330~420px）是左栏「上传 + 文档列表」（`App.tsx:162-190`），第二列是问答（`App.tsx:192-202`）。
- 首屏还有 `.hero` 装饰区（`App.tsx:151-159`，标题 42px、上下 34/44px 间距）与 1310px 最大宽度、`clamp(20px,5vw,72px)` 大留白（`styles.css` 的 `.workspace`、`.hero` 规则），信息密度低。

### 目标布局

```
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：EduRAG 课程知识库 ｜ 课程下拉 ｜ 服务状态              │
├───────────────────────────────────────┬──────────────────────┤
│                                       │  添加课程文档（上）  │
│   课程问答（主模块，内容居中、可滚动） │  ────────────────    │
│   问句输入 / 回答 / 引用              │  课程文档列表（下）  │
│                                       │  （侧栏 sticky）     │
└───────────────────────────────────────┴──────────────────────┘
```

- 栅格改为 `grid-template-columns: minmax(0,1fr) 360px;`，问答在左列、作为视觉主区（内容用 `max-width: 820px; margin: 0 auto;` 居中），右侧栏整体 `position: sticky; top: 16px;`。
- 右栏内部上下两块：上传面板在上、文档列表面板在下；列表区 `max-height: calc(100vh - 380px); overflow-y: auto;`，不再把页面撑长。
- 顶栏由 68px 收到 56px；删除首屏 hero 区，把标题并入问答面板头部；`workspace` 改为 `max-width: 1440px; padding: 24px 32px 40px;`。
- 响应式：`@media (max-width: 1024px)` 折叠为单列（问答在上、上传+列表在下）；`768px` 以下按钮全宽。

### 验收

- 1440 / 1280 / 1024 / 768 四档宽度无横向滚动；首屏即可看到提问框与课程下拉。
- 切换课程、滚动引用时右栏不被拉长；文档多时仅列表内部滚动。

## 3. 回答中的公式与特殊字符显示异常 → Markdown + LaTeX 渲染

### 背景与现象

- 回答里出现 `**加粗**`、`$...$`、`\frac{}`、`^`、`_`、`|表格|`、反引号等原始字符，用户看到的是「很多特殊字符」而不是排版后的内容。

### 原因（代码定位）

- 前端直接按纯文本渲染：`frontend/src/App.tsx:200` 的 `<div className="answer-text">{answer.answer}</div>`，React 对文本做转义，Markdown/LaTeX 不会生效；引用片段同样是纯文本（`App.tsx:211`）。
- 前端没有任何 Markdown/公式依赖：`frontend/package.json:13-20` 只有 react/vite/lucide。
- 后端没有约定输出格式：`src/edurage/rag/prompt.py:10-17` 的系统提示只约束「只依据片段、引用页码」，未要求 Markdown/LaTeX；`answerer.py:47-56` 原样返回模型文本。

### 解决方案

**后端（Prompt 约定输出格式）**

在 `SYSTEM_PROMPT` 增加：输出使用 Markdown；行内公式用 `$...$`、独立公式用 `$$...$$`；代码/表格用 ``` 围栏；无法排版或异常字符用代码块包裹；禁止输出 HTML。

**前端（渲染管线）**

```powershell
cd frontend
npm install react-markdown remark-gfm remark-math rehype-katex katex
```

- 新增 `src/components/AnswerMarkdown.tsx`：`ReactMarkdown` + `remarkGfm` + `remarkMath` + `rehypeKatex`，`skipHtml`（防 XSS），并 `import 'katex/dist/katex.min.css'`。
- `App.tsx:200` 改为 `<AnswerMarkdown content={answer.answer} />`；引用片段（`App.tsx:211`）保持纯文本/Markdown 简单渲染，OCR 乱码可套成代码块。
- 样式：`.answer-text` 内补齐标题/列表/表格/代码块/KaTeX 的排版规则；代码块可选用 `rehype-highlight` 上色。
- 兜底：渲染前把孤立控制字符（如 `\u0000-\u001f`）清洗成空白；渲染异常时回退 `<pre>` 原文，保证不白屏。

### 验收

- 提一个含公式的问题（如「SE[6..1] 的控制信号条件是什么？」），公式按数学排版显示、`**加粗**`/列表/表格/代码块正常。
- 后端 prompt 更新后新回答稳定输出 Markdown；前端构建 `npm run build` 通过、原有 vitest 用例不回归。

## 4. 页面视觉精美化

### 背景与现象

- 缺少统一设计规范：颜色/字号/间距/圆角/阴影各自为政，卡片与留白比例失衡，状态反馈（加载、空、错误）样式不统一。

### 原因（代码定位）

- 样式集中在单个压缩式文件 `frontend/src/styles.css`（一行写完），大量内联结构写在 `App.tsx`；没有组件拆分（上传、列表、问答、引用都是同文件 JSX），难以统一维护。

### 解决方案

1. **设计 token**（`:root` CSS 变量）：主色沿用 `#176b5e`，补充 3 档中性灰阶、成功/警告/错误色；字号阶梯 12/13/14/16/20/24；间距 4/8/16/24/32；圆角 8/12；阴影 3 级。
2. **组件化拆分**（建议 `frontend/src/components/`）：`CourseSelect`、`UploadPanel`、`DocumentList`、`AskPanel`、`CitationCard`、`AnswerMarkdown`、`StatusNotice`；把 `App.tsx` 收敛为状态编排（保留现有测试可达的文案/标签，减少测试改动）。
3. **交互状态**：上传/问答 loading 用骨架屏或进度条替代纯文字「正在处理」；空状态给图标+一句引导；错误提示带 request_id（已有，保留）。
4. **视觉细节**：统一图标尺寸 14/16/18；hover/focus 用 `focus-visible` 2px 主色 outline；过渡 ≤ 200ms；表格/引用卡加细边框与轻阴影；中文标题用 `Noto Sans SC`，数字/英文用 `Inter`。
5. **响应式**：1280/1024/768 三档断点；触屏下按钮高度 ≥ 40px。

### 验收

- 三档宽度截图无错位/溢出；首屏信息密度提升（无大面积空白）；同一类元素（按钮、输入、卡片）在两种宽度下样式一致。

## 5. 一键启动增加后端/LLM 请求监控窗口 + 上传进度可观测

### 背景与现象

- 上传文档后界面一直停在「正在处理…」，不知道是在解析、在等 embedding、还是已经报错；启动脚本只开 API/前端服务，不显示日志。

### 原因（代码定位）

- 上传是**同步长请求**：`upload.py:46-113` 里通过 `asyncio.to_thread`（`upload.py:82-86`）跑完「解析 → 分块 → embedding → 写 Qdrant → 写 PostgreSQL」全程才返回；前端只有按钮文字「正在处理…」（`App.tsx:173`），没有阶段回传。
- 文档记录在 embedding 全部完成后才入库（`indexer.py:243-260` 先 `upsert` 向量、后 `insert_document`），处理期间数据库里查不到这条文档。
- 大文件慢的原因：embedding 按批（`embedding_batch_size=10`，`indexer.py:161`）逐批调用，每批受 `llm_timeout_s=60`（`config.py:51`）限制；若 `OCR_ENABLED=true` 且是扫描版 PDF，还要逐页 OCR（`document_parser.py:48-74`），明显变慢。
- 并发受限：单进程信号量上限 `api_max_concurrency=2`（`config.py:44`、`middleware.py:62-64`），上传进行中再发请求会得到 `503 Server is busy`，容易被误判为崩溃。
- 后端日志是 JSON 单行输出到容器 stdout（`core/logging.py:14-49`，含 request_id / stage / elapsed_ms / status / pages / chunks），但 `start_edurage.bat` 不显示 api 日志，用户看不到这些信息。

### 解决方案 A：`.bat` 增加监控窗口（P0，改动小）

在 `start_edurage.bat:81` 的 `:health_ok` 标签后、`where npm` 之前插入：

```bat
start "EduRAG API 日志（后端 / LLM 请求）" /D "%ROOT%" cmd /k "docker compose logs -f --tail=100 api"
```

- 窗口内直接看到每次请求的 `query completed` / `upload completed` / `api request failed` / `unhandled API failure`，以及 `request_id`、`elapsed_ms`、`stage`；上传是否还在跑一目了然。
- 可选再加一个基础设施窗口：`start "EduRAG 基础设施日志" /D "%ROOT%" cmd /k "docker compose logs -f --tail=50 postgres qdrant minio"`。
- 也可单独提供 `scripts\logs.bat`：`cd /d %~dp0..` + `docker compose logs -f --tail=100 api`，随时双击查看。
- 注意：该 `.bat` 必须保持 **ANSI/GBK 编码 + CRLF 换行**（文件头 `start_edurage.bat:3-10` 已注明），否则又会回到「双击没反应」。

### 解决方案 B：上传进度可观测（P1，根因修复）

1. 上传改异步：`POST /api/v1/upload` 先建文档记录（`status=processing`, `metadata.progress={stage:parse,done:0,total:0}`）并立即返回 `202` + `document_id`，解析/embedding 放后台任务。
2. 新增 `GET /api/v1/documents/{document_id}` 返回状态与进度；embedding 每批完成后更新 `progress`（`stage: embed, done: n, total: batch_total`），完成时置 `status=indexed`，失败置 `status=failed` + `error_code`。
3. 前端上传后每 1–2s 轮询进度，显示「解析中 / 分块中 / 向量化 n/m / 写入索引」进度条；超过 10 分钟提示超时并给出 request_id；保留取消按钮（中止轮询即可）。
4. 兼容策略：一期可先做 A（日志窗口）+ 前端超时提示 + 按钮文案细化（「正在解析并向量化，大文件可能需要数分钟」）；二期再切异步接口，并同步更新 `docs/ed-04-api.md` 与测试（201→202 属 API 契约变更）。
5. 若暂不改上传接口，最小替代：前端在上传请求发出同时轮询 `GET /documents?course_code=...`，看是否出现同名 `processing` 记录（需要后端先把文档行提前入库）。

### 验收

- 上传大文件时，监控窗口能看到 started/completed 各阶段日志；前端显示阶段与百分比，不再「无反馈地卡住」。
- 上传与提问并发时，界面对 503/429 给出明确提示与重试指引。

## 6. 支持 Word 文档（.docx）

### 背景与现象

- 课程资料常见 Word 讲义/实验指导书，目前上传 `.docx` 会被拒绝；前端提示也只写「PDF / PPTX」。

### 原因（代码定位）

- 上传白名单：`src/edurage/api/v1/endpoints/upload.py:22-25`（`CONTENT_TYPES` 只有 .pdf/.pptx）、`:58-63`（扩展名 + MIME 校验）、`:40-43`（文件魔数只判 PDF / ZIP）。
- 解析分发：`src/edurage/ingest/document_parser.py:27-35`（`detect_file_type` 只认 pdf/pptx）、`:38-90`（只有 pdf / pptx 分支）。
- 入库类型映射：`indexer.py:34-37`（MinIO `CONTENT_TYPES` 同样只有两种）；`docs/ed-04-api.md:5-10` 把上传契约限定为 PDF/PPTX；`README.md:606-614`（ED-02 也只声明 PDF/PPTX）。
- 依赖里没有 Word 解析库：`pyproject.toml:11-28`（有 pymupdf、python-pptx，无 python-docx）；前端 `App.tsx:21-23`（`formatType` 只认 PPTX/PDF）、`:167`（`accept` 属性）、`:169-172`（文案）。

### 解决方案

1. 依赖：`pyproject.toml` 加 `python-docx`。
2. 新增 `src/edurage/ingest/docx_parser.py`：
   - 用 `python-docx` 读取段落与表格，按 Heading 样式/分节切块，返回与 PDF/PPTX 相同的 `[{page, text, text_sources}]`；
   - `.docx` 没有真实页码，`page` 定义为「章节/段落块序号」（1 起），引用在 UI 上按 `file_type=docx` 显示为「第 N 节/第 N 段」；
   - 表格转成「行/列 + 表头」文本，保留在 chunk 中。
3. 打通各层：
   - `document_parser.detect_file_type` 增加 `docx`，`parse_document` 增加分支；
   - `upload.py` 的 `CONTENT_TYPES` 增加 `.docx`（MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document`），魔数校验复用 `PK` 并校验 zip 内含 `word/document.xml`；
   - `indexer.py:34-37` 的 MinIO 类型映射增加 docx；错误提示改为「Only PDF, PPTX, and DOCX files are accepted」；
   - 前端 `accept=".pdf,.pptx,.docx,..."`、`formatType` 支持 DOCX、dropzone 文案改「选择或拖入 PDF / PPTX / DOCX」。
4. 明确边界：只支持 `.docx`；`.doc`（旧二进制格式）返回 `unsupported_file_type`，文案提示另存为 `.docx`。
5. 文档与测试：更新 `docs/ed-04-api.md:5-10`、`README.md:606-614`；新增 `tests/` 下 docx 解析单测 + 上传 MIME/魔数用例；可选补一个 e2e 样例。

### 验收

- 上传 .docx 成功返回 201 + chunks；问答能命中其中内容，引用显示「第 N 节/段」；
- `.doc` / 伪装扩展名（改后缀的 zip/文本）返回 400，错误码正确；前端文件选择器可选中 docx。

## 7. 实施顺序与工作量

| 顺序 | 内容 | 预估 | 依赖/说明 |
|------|------|------|-----------|
| 1 | 5-A `.bat` 日志窗口 + 前端上传超时/文案 | 0.5h | 立即缓解「卡死不可见」 |
| 2 | 3 Markdown + LaTeX 渲染（前后端） | 0.5d | 独立、见效快 |
| 3 | 1 课程接口 + 配置同步 + 下拉实时切换（含 DB 迁移） | 1.5d | 需先定迁移方式（Alembic / 手工 ALTER） |
| 4 | 2 布局重排（问答居中 + 右侧上下栏） | 1.5d | 会动 App.test.tsx，测试同步改 |
| 5 | 5-B 上传异步 + 进度轮询 | 1.5–2d | 改 API 契约 201→202，需同步文档/测试 |
| 6 | 6 DOCX 支持 | 1d | 依赖 python-docx，改动集中在解析/上传层 |
| 7 | 4 视觉精美化（组件拆分 + token 化） | 1–2d | 建议跟随 2 一起做，避免二次改样式 |

合计约 5.5–7 人日。建议 5-A → 3 → 1 → 2/4 → 6 → 5-B；若「卡死」影响验收，可把 5-B 提前到 4 之前。

## 8. 回归与验收清单

- 后端：`python -m ruff check .` + `python -m pytest -q` 全绿（新增课程/进度/docx 用例）。
- 前端：`npm run test` + `npm run build` 通过（改造后同步更新 `App.test.tsx`：课程输入改为下拉、`课程代码` label 相关断言、答案渲染断言）。
- 容器：`docker compose up -d --build api` 后 `docker compose ps` 全 healthy、`GET /api/v1/health` 仍返回冻结契约 `{"status":"ok","service":"edurage","version":"0.0.1"}`。
- 端到端：下拉切换课程 → 上传 PDF/PPTX/DOCX → 监控窗口可见日志 → 提问含公式 → 引用页码正确。
- 约束：不改 `.env` 的 39 个 `EDURAGE_*` 键契约（`tests/test_env_contract.py`）；不打印/提交任何真实 Key；`.bat` 改动保持 GBK+CRLF。

## 9. 涉及文件清单

- 前端：`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/styles.css`、`frontend/package.json`、`frontend/src/App.test.tsx`（+ 新 `frontend/src/components/*`）。
- 后端：`src/edurage/api/v1/router.py`、`src/edurage/api/v1/endpoints/upload.py`、`.../documents.py`、`src/edurage/api/schemas.py`、`src/edurage/db/{models,repository}.py`、`src/edurage/courses/{loader,schema}.py`（+ 新 `sync.py`）、`src/edurage/ingest/{document_parser,indexer}.py`（+ 新 `docx_parser.py`）、`src/edurage/rag/prompt.py`、`src/edurage/main.py`、`scripts/init_db.py`。
- 配置与脚本：`configs/course_packs/*.yaml`、`start_edurage.bat`（+ 可选 `scripts/logs.bat`）、`pyproject.toml`。
- 文档：`README.md`、`docs/ed-04-api.md`、`docs/development.md`。
