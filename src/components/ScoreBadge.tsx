import React from 'react';
import { Star } from 'lucide-react';

interface ScoreTone {
  text: string;
  bar: string;
}

// Asteikko vastaa backendin app/scoring.py:n jakaumaa: 75+ = kuuma liidi
const scoreTone = (score: number): ScoreTone => {
  if (score >= 75) return { text: 'text-score-hot', bar: 'bg-score-hot' };
  if (score >= 50) return { text: 'text-score-good', bar: 'bg-score-good' };
  if (score >= 25) return { text: 'text-score-fair', bar: 'bg-score-fair' };
  return { text: 'text-score-low', bar: 'bg-score-low' };
};

export const ScoreBadge: React.FC<{ score: number | null | undefined; meter?: boolean }> = ({
  score,
  meter = true,
}) => {
  if (score === null || score === undefined) {
    return <span className="text-xs text-fg-subtle">-</span>;
  }
  const tone = scoreTone(score);
  return (
    <span title="Lead score (0-100)" className="inline-flex items-center gap-2">
      <span className={`w-5 text-sm font-semibold tabular-nums ${tone.text}`}>{score}</span>
      {meter && (
        <span aria-hidden="true" className="h-[3px] w-7 bg-line-strong">
          <span
            className={`block h-full ${tone.bar}`}
            style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
          />
        </span>
      )}
    </span>
  );
};

export const RatingDisplay: React.FC<{
  rating: number | null | undefined;
  reviewCount: number | null | undefined;
}> = ({ rating, reviewCount }) => {
  if (!reviewCount) {
    return <span className="text-xs text-fg-subtle italic">No reviews</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 text-sm text-fg tabular-nums whitespace-nowrap">
      <Star size={12} className="text-warning fill-warning shrink-0" />
      {rating !== null && rating !== undefined ? rating.toFixed(1) : '-'}
      <span className="text-fg-subtle">({reviewCount})</span>
    </span>
  );
};

const STATUS_STYLE: Record<string, { dot: string; label: string }> = {
  'NO WEBSITE': { dot: 'bg-status-none', label: 'No website' },
  'BROKEN WEBSITE': { dot: 'bg-status-broken', label: 'Broken website' },
  INSECURE: { dot: 'bg-status-insecure', label: 'Insecure' },
  'NOT MOBILE': { dot: 'bg-status-mobile', label: 'Not mobile' },
  UNKNOWN: { dot: 'bg-status-unknown', label: 'Unknown' },
  'WEBSITE OK': { dot: 'bg-status-ok', label: 'Website OK' },
};

export const StatusBadge: React.FC<{ status: string; title?: string }> = ({ status, title }) => {
  const style = STATUS_STYLE[status] ?? { dot: 'bg-status-unknown', label: status };
  return (
    <span title={title} className="inline-flex items-center gap-1.5 text-sm font-medium text-fg whitespace-nowrap">
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  );
};
