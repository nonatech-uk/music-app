interface Props {
  offset: number
  limit: number
  total: number
  hasMore: boolean
  onChange: (offset: number) => void
}

export default function Pagination({ offset, limit, total, hasMore, onChange }: Props) {
  if (total <= limit && offset === 0) return null

  return (
    <div className="flex items-center justify-between text-sm text-text-secondary pt-4">
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="px-3 py-1 rounded border border-border disabled:opacity-30 hover:bg-bg-hover"
        >
          Previous
        </button>
        <button
          onClick={() => onChange(offset + limit)}
          disabled={!hasMore}
          className="px-3 py-1 rounded border border-border disabled:opacity-30 hover:bg-bg-hover"
        >
          Next
        </button>
      </div>
    </div>
  )
}
