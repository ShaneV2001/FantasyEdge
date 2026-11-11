// frontend/src/components/chat/types.ts
export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  toolStatus?: Array<{
    name: string
    status: 'start' | 'done' | 'error'
    label?: string
  }>
  createdAt: Date
}

export interface ChatSummaryOut {
  id: string
  title: string
  model: string
  updated_at: string
}

export interface ChatRequest {
  message: string
  conversation_id?: string | null
}

export interface SSEMeta {
  conversation_id: string
  model: string
}

export interface SSEDone {
  stop_reason: string
  usage: {
    input_tokens: number
    output_tokens: number
  }
}
