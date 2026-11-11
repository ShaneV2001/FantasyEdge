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
  selectConversation: (id: string | null) => void
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
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Chat request failed')
      }

      // Parse SSE stream
      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let assistantContent = ''
      let toolStatus: ChatMessage['toolStatus'] = []
      let assistantMsg: ChatMessage | null = null
      let newConversationId = conversationId

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (!line.trim()) continue
          if (!line.startsWith('data: ')) continue

          const data = line.slice(6) // Remove 'data: '
          const event = JSON.parse(data)

          if (event.conversation_id && event.model) {
            // meta event
            newConversationId = event.conversation_id
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
          } else if (event.stop_reason) {
            // done event
            refetchConversations()
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'))
    } finally {
      setIsLoading(false)
    }
  }

  const selectConversation = (id: string | null) => {
    setConversationId(id)
    setMessages([])
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
