import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Select } from '@/components/ui/Select';
import { IconButton } from '@/components/ui/IconButton';

const PAGE_SIZES = [10, 25, 50, 100];

export function ProfilesPagination({
  page,
  pageSize,
  total,
  totalPages,
  onPage,
  onPageSize,
}: {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-[13px] text-ink-muted">
      <span aria-live="polite">
        {total === 0 ? (
          'No profiles'
        ) : (
          <>
            Showing <span className="text-ink">{from}</span>–<span className="text-ink">{to}</span>{' '}
            of <span className="text-ink">{total}</span>
          </>
        )}
      </span>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          <span className="text-ink-faint">Rows</span>
          <Select
            className="h-8 w-[74px]"
            value={String(pageSize)}
            onChange={(e) => onPageSize(Number(e.target.value))}
            options={PAGE_SIZES.map((size) => ({ value: String(size), label: String(size) }))}
          />
        </label>

        <div className="flex items-center gap-2">
          <IconButton
            label="Previous page"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </IconButton>
          <span className="min-w-[72px] text-center">
            Page <span className="text-ink">{page}</span> / {totalPages}
          </span>
          <IconButton
            label="Next page"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => onPage(page + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
