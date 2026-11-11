import { useCallback, useRef, useState } from 'react'
import { Card } from '@/components/ui/card'
import { ChatHeader } from './ChatHeader'
import { ChatMessages } from './ChatMessages'
import { ChatInput } from './ChatInput'
import { useChat } from './useChat'

interface ChatPanelProps {
  teamId: string
}

export function ChatPanel({ teamId }: ChatPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [panelHeight, setPanelHeight] = useState(300)
  const isDraggingRef = useRef(false)
  const startYRef = useRef(0)
  const startHeightRef = useRef(0)

  const {
    messages,
    conversationId,
    isLoading,
    conversations,
    error,
    sendMessage,
    selectConversation,
    startNewChat,
  } = useChat(teamId)

  const handleMouseDown = (e: React.MouseEvent) => {
    isDraggingRef.current = true
    startYRef.current = e.clientY
    startHeightRef.current = panelHeight
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDraggingRef.current) return
    const delta = startYRef.current - e.clientY
    const newHeight = Math.max(200, Math.min(600, startHeightRef.current + delta))
    setPanelHeight(newHeight)
  }, [])

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }, [handleMouseMove])

  return (
    <Card className="flex flex-col border-t border-l-0 border-r-0 border-b-0">
      {/* Resize handle */}
      {isExpanded && (
        <div
          onMouseDown={handleMouseDown}
          className="h-1 cursor-row-resize bg-border hover:bg-primary/50"
        />
      )}

      {/* Header */}
      <ChatHeader
        isExpanded={isExpanded}
        onToggle={() => setIsExpanded(!isExpanded)}
        conversationId={conversationId}
        conversations={conversations}
        onSelectConversation={selectConversation}
        onNewChat={startNewChat}
      />

      {/* Content (only when expanded) */}
      {isExpanded && (
        <div style={{ height: panelHeight }} className="flex flex-col">
          {error && (
            <div className="border-b border-border bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-300">
              {error.message}
            </div>
          )}
          <ChatMessages messages={messages} isLoading={isLoading} />
          <ChatInput
            onSend={sendMessage}
            isLoading={isLoading}
            disabled={false}
          />
        </div>
      )}
    </Card>
  )
}
