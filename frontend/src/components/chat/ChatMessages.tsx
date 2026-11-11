import { useEffect, useRef } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { ChatMessage as ChatMessageType } from './types'
import { Badge } from '@/components/ui/badge'
import { Check, AlertCircle, Loader2 } from 'lucide-react'

interface ChatMessagesProps {
  messages: ChatMessageType[]
  isLoading: boolean
}

export function ChatMessages({ messages, isLoading }: ChatMessagesProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isLoading])

  const getToolIcon = (status: string) => {
    switch (status) {
      case 'start':
        return <Loader2 className="h-3 w-3 animate-spin" />
      case 'done':
        return <Check className="h-3 w-3" />
      case 'error':
        return <AlertCircle className="h-3 w-3" />
      default:
        return null
    }
  }

  return (
    <div
      ref={scrollRef}
      className="flex flex-col gap-3 overflow-y-auto p-3"
      style={{ height: 'calc(100% - 60px)' }}
    >
      {messages.length === 0 && !isLoading && (
        <div className="text-center text-sm text-muted-foreground">
          Ask me about your team, trades, lineup, or injuries.
        </div>
      )}

      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div
            className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
              msg.role === 'user'
                ? 'bg-blue-100 text-blue-900 dark:bg-blue-900 dark:text-blue-100'
                : 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
            }`}
          >
            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
            {msg.toolStatus && msg.toolStatus.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {msg.toolStatus.map((tool) => (
                  <Badge
                    key={tool.name}
                    variant="secondary"
                    className="flex items-center gap-1 text-xs"
                  >
                    {getToolIcon(tool.status)}
                    {tool.label || tool.name}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}

      {isLoading && (
        <div className="flex justify-start">
          <Skeleton className="h-10 w-32 rounded-lg" />
        </div>
      )}
    </div>
  )
}
