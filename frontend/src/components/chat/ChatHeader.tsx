import {
  ChevronUp,
  ChevronDown,
  Plus,
  MessageSquare,
  Minus,
} from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { ChatSummaryOut } from './types'

interface ChatHeaderProps {
  isExpanded: boolean
  onToggle: () => void
  conversationId: string | null
  conversations: ChatSummaryOut[]
  onSelectConversation: (id: string | null) => void
  onNewChat: () => void
}

export function ChatHeader({
  isExpanded,
  onToggle,
  conversationId,
  conversations,
  onSelectConversation,
  onNewChat,
}: ChatHeaderProps) {
  return (
    <div className="flex items-center justify-between border-t border-border bg-card px-3 py-2">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggle}
          className="h-6 w-6 p-0"
        >
          {isExpanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </Button>
        <MessageSquare className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">Chat</span>

        {isExpanded && (
          <Select
            value={conversationId || '__new__'}
            onValueChange={(value) =>
              onSelectConversation(value === '__new__' ? null : value)
            }
          >
            <SelectTrigger className="h-8 w-48 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__new__">New chat</SelectItem>
              {conversations.map((conv) => (
                <SelectItem key={conv.id} value={conv.id}>
                  {conv.title || 'Untitled'}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {isExpanded && (
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={onNewChat} className="h-6 w-6 p-0">
            <Plus className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onToggle} className="h-6 w-6 p-0">
            <Minus className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
