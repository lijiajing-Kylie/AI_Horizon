import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getRunDates } from '../api/client'
import { todayStr } from '../utils/date'

interface DailyCalendarProps {
  selectedDate: string | null
  onSelectDate: (date: string) => void
}

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']
const pad = (n: number) => String(n).padStart(2, '0')

export default function DailyCalendar({ selectedDate, onSelectDate }: DailyCalendarProps) {
  const [shownMonth, setShownMonth] = useState(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const { data: runDates } = useApi(() => getRunDates(365), [])
  const availableDates = new Set(runDates || [])
  const today = todayStr()

  const year = shownMonth.getFullYear()
  const month = shownMonth.getMonth()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  // Monday-first grid: getDay() is 0=Sun..6=Sat.
  const leadingBlanks = (new Date(year, month, 1).getDay() + 6) % 7

  const cells: (string | null)[] = [
    ...Array(leadingBlanks).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => `${year}-${pad(month + 1)}-${pad(i + 1)}`),
  ]

  return (
    <div className="glass rounded-[22px] p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={() => setShownMonth(new Date(year, month - 1, 1))}
          aria-label="上个月"
          className="w-7 h-7 flex items-center justify-center rounded-lg border border-[#d8dee5] bg-white text-[#708096] hover:bg-gray-50"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>
        <strong className="text-sm text-[#3d4a5f]">{year}年{month + 1}月</strong>
        <button
          onClick={() => setShownMonth(new Date(year, month + 1, 1))}
          aria-label="下个月"
          className="w-7 h-7 flex items-center justify-center rounded-lg border border-[#d8dee5] bg-white text-[#708096] hover:bg-gray-50"
        >
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-7 text-center text-[10px] text-[#8b97a8] mb-1">
        {WEEKDAY_LABELS.map(d => <div key={d}>{d}</div>)}
      </div>

      <div className="grid grid-cols-7 gap-1.5">
        {cells.map((date, i) => {
          if (!date) return <div key={`blank-${i}`} />
          const hasData = availableDates.has(date)
          const isToday = date === today
          const isSelected = date === selectedDate
          return (
            <button
              key={date}
              disabled={!hasData}
              onClick={() => onSelectDate(date)}
              className={`aspect-square rounded-full text-xs flex items-center justify-center transition-colors ${
                isSelected
                  ? 'bg-[var(--accent)]/70 text-white font-semibold'
                  : isToday
                    ? 'bg-[#edf4fc] text-[var(--accent)] font-semibold ring-1 ring-inset ring-[#9ebfe3]'
                    : hasData
                      ? 'text-[#45536a] hover:bg-[#edf4fc] cursor-pointer'
                      : 'text-[#c3cad4] cursor-default'
              }`}
            >
              {Number(date.slice(-2))}
            </button>
          )
        })}
      </div>
    </div>
  )
}
