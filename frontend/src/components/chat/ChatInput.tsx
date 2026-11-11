import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Send } from 'lucide-react'

interface ChatInputProps {
  onSend: (message: string) => Promise<void>
  isLoading: boolean
  disabled?: boolean
}

export function ChatInput({ onSend, isLoading, disabled = false }: ChatInputProps) {
  const [text, setText] = useState('')

  const handleSend = async () => {
    if (!text.trim() || isLoading || disabled) return
    await onSend(text)
    setText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex gap-2 border-t border-border p-3">
      <Textarea
        placeholder="Ask about your team..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isLoading || disabled}
        className="min-h-10 resize-none"
        rows={1}
      />
      <Button
        onClick={handleSend}
        disabled={!text.trim() || isLoading || disabled}
        size="sm"
      >
        <Send className="h-4 w-4" />
      </Button>
    </div>
  )
}
