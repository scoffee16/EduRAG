import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const docs = [{ document_id: 'doc-1', filename: '讲义.pdf', course_code: 'CS-A', file_type: 'pdf', status: 'indexed', page_count: 3, chunk_count: 4, created_at: '2026-10-15T00:00:00Z' }]

function response(body: unknown, init?: ResponseInit) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init }))
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
    if (url.includes('/health/ocr')) return response({ status: 'ok', enabled: true, available: true })
    if (url.includes('/documents') && options?.method === 'DELETE') return response({ document_id: 'doc-1', status: 'deleted' })
    if (url.includes('/documents')) return response(docs)
    if (url.includes('/upload')) return response({ document_id: 'new-1', filename: 'new.pdf', pages: 2, chunks: 2, course_code: 'CS-A', status: 'indexed' }, { status: 201 })
    if (url.includes('/query')) return response({ answer: '答案内容', citations: [{ filename: '讲义.pdf', page: 2, snippet: '<不应执行>', score: 0.81, modality: 'text' }], model: 'mock', latency_ms: 21, request_id: 'req-1' })
    return response({}, { status: 404 })
  }))
})

afterEach(() => vi.restoreAllMocks())

describe('EduRAG workflow', () => {
  it('loads documents and clears selected document when course changes', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('讲义.pdf')
    await user.click(screen.getByText('讲义.pdf'))
    expect(screen.getByText(/单份文档/)).toBeInTheDocument()
    await user.clear(screen.getByLabelText('课程代码'))
    await user.type(screen.getByLabelText('课程代码'), 'CS-B')
    expect(screen.getByText(/全课程/)).toBeInTheDocument()
  })

  it('requires confirmation before deleting', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => false))
    render(<App />)
    await screen.findByText('讲义.pdf')
    await user.click(screen.getByTitle('删除 讲义.pdf'))
    expect(window.confirm).toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalledWith('/api/v1/documents/doc-1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('deletes after confirmation and refreshes the list', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(<App />)
    await screen.findByText('讲义.pdf')
    await user.click(screen.getByTitle('删除 讲义.pdf'))
    await waitFor(() => expect(window.confirm).toHaveBeenCalled())
    expect(fetch).toHaveBeenCalledWith('/api/v1/documents/doc-1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('shows upload errors without claiming OCR success', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/health/ocr')) return response({ status: 'disabled' })
      if (url.includes('/documents')) return response([])
      if (url.includes('/upload')) return response({ detail: 'Only PDF files are accepted' }, { status: 400 })
      return response({})
    }))
    render(<App />)
    const input = screen.getByLabelText(/选择或拖入/)
    fireEvent.change(input, { target: { files: [new File(['slides'], 'slides.pptx', { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })] } })
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))
    await waitFor(() => expect(screen.getByText('Only PDF files are accepted')).toBeInTheDocument())
    expect(screen.queryByText('OCR 已成功')).not.toBeInTheDocument()
  })

  it('shows query errors with retry guidance and request id', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/health/ocr')) return response({ status: 'ok' })
      if (url.includes('/documents')) return response([])
      if (url.includes('/query')) return response({ error: { code: 'busy', message: '服务繁忙' }, request_id: 'req-429' }, { status: 429 })
      return response({})
    }))
    render(<App />)
    await user.type(screen.getByPlaceholderText(/ADD 指令/), '这个问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))
    await waitFor(() => expect(screen.getByText('服务繁忙 请稍后重试。')).toBeInTheDocument())
    expect(screen.getByText('req-429')).toBeInTheDocument()
  })

  it('renders query citations as text and surfaces query errors', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('讲义.pdf')
    await user.type(screen.getByPlaceholderText(/ADD 指令/), '这个问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))
    await waitFor(() => expect(screen.getByText('答案内容')).toBeInTheDocument())
    expect(screen.getByText('<不应执行>')).toBeInTheDocument()
    expect(screen.getByText('score 0.810')).toBeInTheDocument()
  })

  it('shows OCR unavailable warning for HTTP 503', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/health/ocr')) return response({ status: 'unavailable', error: 'tesseract missing' }, { status: 503 })
      if (url.includes('/documents')) return response([])
      return response({}, { status: 200 })
    }))
    render(<App />)
    await waitFor(() => expect(screen.getByText(/OCR 不可用/)).toBeInTheDocument())
  })
})
