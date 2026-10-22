# EduRAG Web UI

## 开发

在 `frontend` 目录执行：

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`。Vite 将同源 `/api` 请求代理到
`http://127.0.0.1:8000`，可用 `EDURAGE_API_PROXY` 覆盖代理地址：

```powershell
$env:EDURAGE_API_PROXY="http://127.0.0.1:8000"
npm run dev
```

## 构建与测试

```powershell
npm run build
npm test
```

测试使用 mock API，不代表真实后端联调成功。不要在浏览器或 `VITE_*` 变量中放置
DeepSeek、DashScope 或其他密钥。

## 联调说明

前端文件选择支持 PDF/PPTX/DOCX，后端上传接口也接受这三种格式，可直接联调。前端不会把
上传成功推断为 OCR 成功，OCR 状态始终来自 `GET /api/v1/health/ocr`。
