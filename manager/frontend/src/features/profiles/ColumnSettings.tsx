import { ChevronDown, ChevronUp, Columns3 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Popover } from '@/components/ui/Popover';
import { Checkbox } from '@/components/ui/Checkbox';
import { IconButton } from '@/components/ui/IconButton';
import { useUiStore } from '@/app/uiStore';
import { COLUMN_META } from './columns';

const LOCKED_FIRST = 'select';
const LOCKED_LAST = 'actions';

export function ColumnSettings() {
  const columnVisibility = useUiStore((state) => state.columnVisibility);
  const setColumnVisible = useUiStore((state) => state.setColumnVisible);
  const columnOrder = useUiStore((state) => state.columnOrder);
  const setColumnOrder = useUiStore((state) => state.setColumnOrder);

  const known = COLUMN_META.map((c) => c.id);
  const order = columnOrder.length
    ? [
        ...columnOrder.filter((id) => known.includes(id)),
        ...known.filter((id) => !columnOrder.includes(id)),
      ]
    : known;
  const meta = new Map(COLUMN_META.map((c) => [c.id, c]));

  const move = (id: string, direction: -1 | 1) => {
    const index = order.indexOf(id);
    const target = index + direction;
    if (target < 1 || target > order.length - 2) return; // keep select first, actions last
    if (order[target] === LOCKED_FIRST || order[target] === LOCKED_LAST) return;
    const next = [...order];
    [next[index], next[target]] = [next[target], next[index]];
    setColumnOrder(next);
  };

  return (
    <Popover
      align="end"
      width={264}
      trigger={
        <IconButton label="Column settings">
          <Columns3 className="h-4 w-4" />
        </IconButton>
      }
    >
      <div className="space-y-1">
        <p className="px-1 pb-1 text-[13px] font-semibold text-ink">Columns</p>
        {order.map((id) => {
          const column = meta.get(id)!;
          const locked = id === LOCKED_FIRST || id === LOCKED_LAST;
          const reorderable = !locked;
          return (
            <div
              key={id}
              className="flex items-center gap-1.5 rounded px-1 py-1 hover:bg-surface-sunken"
            >
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={`Move ${column.label} up`}
                  disabled={!reorderable}
                  onClick={() => move(id, -1)}
                  className="text-ink-faint hover:text-ink disabled:opacity-30"
                >
                  <ChevronUp className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  aria-label={`Move ${column.label} down`}
                  disabled={!reorderable}
                  onClick={() => move(id, 1)}
                  className="text-ink-faint hover:text-ink disabled:opacity-30"
                >
                  <ChevronDown className="h-3 w-3" />
                </button>
              </div>
              <span className="flex-1 text-[13px] text-ink">{column.label}</span>
              <label className="flex items-center">
                <span className="sr-only">Show {column.label}</span>
                <Checkbox
                  checked={column.canHide ? columnVisibility[id] !== false : true}
                  disabled={!column.canHide}
                  onChange={(e) => setColumnVisible(id, e.currentTarget.checked)}
                />
              </label>
            </div>
          );
        })}
      </div>
    </Popover>
  );
}
