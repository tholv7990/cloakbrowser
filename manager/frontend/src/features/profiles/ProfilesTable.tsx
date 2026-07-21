import { useMemo } from 'react';
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type RowSelectionState,
  type VisibilityState,
} from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import type { ProfileSort, ProfileView } from '@/types/api';
import { useUiStore } from '@/app/uiStore';
import { cn } from '@/lib/cn';
import { buildColumns, COLUMN_META, SORTABLE } from './columns';
import type { RowDialog } from './ProfileRowActions';

function computeVisibility(stored: Record<string, boolean>): VisibilityState {
  const visibility: VisibilityState = {};
  for (const column of COLUMN_META) {
    visibility[column.id] = column.canHide ? stored[column.id] !== false : true;
  }
  return visibility;
}

function orderedIds(stored: string[]): string[] {
  const known = COLUMN_META.map((c) => c.id);
  if (stored.length === 0) return known;
  const inStored = stored.filter((id) => known.includes(id));
  const missing = known.filter((id) => !inStored.includes(id));
  return [...inStored, ...missing];
}

export function ProfilesTable({
  data,
  sort,
  onToggleSort,
  rowSelection,
  onRowSelectionChange,
  onDialog,
  onTogglePin,
  profileRoot,
}: {
  data: ProfileView[];
  sort: ProfileSort;
  onToggleSort: (columnId: string) => void;
  rowSelection: RowSelectionState;
  onRowSelectionChange: (updater: RowSelectionState) => void;
  onDialog: (dialog: RowDialog, profile: ProfileView) => void;
  onTogglePin: (profile: ProfileView) => void;
  profileRoot: string;
}) {
  const columnVisibility = useUiStore((state) => state.columnVisibility);
  const columnOrder = useUiStore((state) => state.columnOrder);

  const columns = useMemo(
    () => buildColumns(onDialog, onTogglePin, profileRoot),
    [onDialog, onTogglePin, profileRoot],
  );

  const meta = useMemo(() => new Map(COLUMN_META.map((c) => [c.id, c])), []);
  const activeSortColumn = sort.replace(/^-/, '');
  const sortDir = sort.startsWith('-') ? 'desc' : 'asc';

  const table = useReactTable({
    data,
    columns,
    state: {
      rowSelection,
      columnVisibility: computeVisibility(columnVisibility),
      columnOrder: orderedIds(columnOrder),
    },
    enableRowSelection: true,
    getRowId: (row) => row.id,
    onRowSelectionChange: (updater) => {
      onRowSelectionChange(typeof updater === 'function' ? updater(rowSelection) : updater);
    },
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-surface">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-line">
              {headerGroup.headers.map((header) => {
                const columnMeta = meta.get(header.column.id);
                const sortKey = SORTABLE[header.column.id];
                const isActive = sortKey === activeSortColumn;
                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={
                      isActive ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined
                    }
                    className={cn(
                      'whitespace-nowrap px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint',
                      columnMeta?.headClassName,
                    )}
                  >
                    {sortKey ? (
                      <button
                        type="button"
                        onClick={() => onToggleSort(sortKey)}
                        className="inline-flex items-center gap-1 rounded hover:text-ink"
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {isActive ? (
                          sortDir === 'asc' ? (
                            <ArrowUp className="h-3 w-3 text-accent" />
                          ) : (
                            <ArrowDown className="h-3 w-3 text-accent" />
                          )
                        ) : (
                          <ChevronsUpDown className="h-3 w-3 opacity-50" />
                        )}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className={cn(
                'border-b border-line/60 transition-colors hover:bg-surface-sunken/50',
                row.getIsSelected() && 'bg-accent/5',
              )}
            >
              {row.getVisibleCells().map((cell) => {
                const columnMeta = meta.get(cell.column.id);
                return (
                  <td
                    key={cell.id}
                    className={cn('px-3 py-2 align-middle', columnMeta?.cellClassName)}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
