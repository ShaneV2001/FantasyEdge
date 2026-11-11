// frontend/src/components/chat/useChat.ts
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChatMessage, ChatSummaryOut, SSEMeta, SSEDone } from './types'

interface UseChatReturn {
  messages: ChatMessage[]
  conversationId: string | null
  isLoading: boolean
  conversations: ChatSummaryOut[]
  conversationsError: Error | null
  error: Error | null
  sendMessage: (text: string) => Promise<void>
  selectConversation: (id: string | null) => Promise<void>
  startNewChat: () => void
}

export function useChat(teamId: string): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const messageIdRef = useRef(0)

  // Fetch previous conversations
  const {
    data: conversations = [],
    error: conversationsError,
    refetch: refetchConversations,
  } = useQuery({
    queryKey: ['chats', teamId],
    queryFn: async () => {
      const response = await fetch(`/api/team/${teamId}/chats`)
      if (!response.ok) throw new Error('Failed to fetch conversations')
      return response.json() as Promise<ChatSummaryOut[]>
    },
  })

  const sendMessage = async (text: string) => {
    if (!text.trim()) return
    if (isLoading) return

    // Add user message to UI immediately
    const userMsg: ChatMessage = {
      id: `user-${++messageIdRef.current}`,
      role: 'user',
      content: text,
      createdAt: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setError(null)
    setIsLoading(true)

    try {
      const response = await fetch(`/api/team/${teamId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
        }),
      })

      if (!response.ok) {
        let detail = ''
        try {
          const errorData = await response.json()
          detail = errorData.detail || ''
        } catch {
          // body not JSON
        }
        throw new Error(detail || `HTTP ${response.status}: Chat request failed`)
      }

      // Parse SSE stream
      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''
      let assistantContent = ''
      let toolStatus: ChatMessage['toolStatus'] = []
      let assistantMsg: ChatMessage | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')

        // Keep the last (potentially incomplete) line in the buffer
        buffer = lines[lines.length - 1] || ''

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i]
          if (!line.trim()) continue
          if (!line.startsWith('data: ')) continue

          try {
          const event = JSON.parse(line.slice(6))

          if (event.conversation_id && event.model) {
            // meta event
            setConversationId(event.conversation_id)
          } else if (event.text) {
            // text chunk
            assistantContent += event.text
            if (!assistantMsg) {
              assistantMsg = {
                id: `assistant-${++messageIdRef.current}`,
                role: 'assistant',
                content: assistantContent,
                toolStatus,
                createdAt: new Date(),
              }
              setMessages((prev) => [...prev, assistantMsg!])
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg!.id
                    ? { ...m, content: assistantContent }
                    : m
                )
              )
            }
          } else if (event.name && event.status) {
            // tool event
            toolStatus = toolStatus.filter((t) => t.name !== event.name)
            toolStatus.push({
              name: event.name,
              status: event.status,
              label: event.label,
            })
            if (assistantMsg) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, toolStatus } : m
                )
              )
            }
          } else if (event.message || (event.error && event.error.message)) {
            // error event (backend sends {message}; also accept {error: {message}})
            setError(new Error(event.message || event.error.message))
          } else if (event.stop_reason) {
            // done event
            refetchConversations()
          }
          } catch (parseErr) {
            // JSON parse error in an event line; log but continue
            console.error('Failed to parse SSE event:', parseErr)
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'))
    } finally {
      setIsLoading(false)
    }
  }

  const selectConversation = async (id: string | null) => {
    setConversationId(id)
    setMessages([])
    setError(null)

    // Load message history if resuming an existing chat
    if (id) {
      try {
        const response = await fetch(`/api/chats/${id}`)
        if (!response.ok) throw new Error('Failed to load chat history')
        const chat = (await response.json()) as {
          messages: Array<{ role: 'user' | 'assistant'; text: string; tools: string[] }>
        }
        setMessages(
          chat.messages.map((m) => ({
            id: `${m.role}-${++messageIdRef.current}`,
            role: m.role,
            content: m.text,
            createdAt: new Date(),
          }))
        )
      } catch (err) {
        // If history load fails, user can still continue the chat
        console.error('Could not load chat history:', err)
      }
    }
  }

  const startNewChat = () => {
    setConversationId(null)
    setMessages([])
    setError(null)
  }

  return {
    messages,
    conversationId,
    isLoading,
    conversations,
    conversationsError: conversationsError as Error | null,
    error,
    sendMessage,
    selectConversation,
    startNewChat,
  }
}
