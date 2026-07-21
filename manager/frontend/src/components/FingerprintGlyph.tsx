import { useMemo } from 'react';

/**
 * Signature element. Renders a deterministic, symmetric glyph from a profile's
 * stable fingerprint seed — every synthetic identity gets a recognizable mark,
 * tying the dense profile table to CloakBrowser's actual domain (stable seeds).
 * Monochrome accent by design; the *pattern* differentiates, not the color.
 */
function hashSeed(seed: string): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function FingerprintGlyph({ seed, size = 22 }: { seed: string; size?: number }) {
  const cells = useMemo(() => {
    const hash = hashSeed(seed);
    const grid: boolean[][] = [];
    for (let row = 0; row < 5; row += 1) {
      const line: boolean[] = [];
      for (let col = 0; col < 3; col += 1) {
        const bit = (hash >> (row * 3 + col)) & 1;
        line[col] = bit === 1;
      }
      // Mirror the left three columns onto the right for symmetry.
      line[3] = line[1];
      line[4] = line[0];
      grid.push(line);
    }
    return grid;
  }, [seed]);

  const unit = size / 5;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      className="shrink-0 rounded-[3px] bg-surface-sunken"
    >
      {cells.flatMap((line, row) =>
        line.map((filled, col) =>
          filled ? (
            <rect
              key={`${row}-${col}`}
              x={col * unit + 0.5}
              y={row * unit + 0.5}
              width={unit - 1}
              height={unit - 1}
              rx={1}
              className="fill-accent"
            />
          ) : null,
        ),
      )}
    </svg>
  );
}
