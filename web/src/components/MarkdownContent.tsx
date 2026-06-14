import ReactMarkdown from "react-markdown"

interface Props {
  content: string
}

export function MarkdownContent({ content }: Props) {
  return (
    <div className="markdown-content text-sm text-text-secondary leading-relaxed">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
