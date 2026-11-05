import React from 'react';
import { Star } from 'lucide-react';

// Asteikko vastaa backendin app/scoring.py:n jakaumaa: 75+ = kuuma liidi
const scoreStyles = (score: number): string => {
  if (score >= 75) return 'bg-emerald-100 text-emerald-800 border-emerald-200';
  if (score >= 50) return 'bg-lime-100 text-lime-800 border-lime-200';
  if (score >= 25) return 'bg-amber-100 text-amber-800 border-amber-200';
  return 'bg-slate-100 text-slate-600 border-slate-200';
};

export const ScoreBadge: React.FC<{ score: number | null | undefined }> = ({ score }) => {
  if (score === null || score === undefined) {
    return <span className="text-xs text-slate-400">-</span>;
  }
  return (
    <span
      title="Lead score (0-100)"
      className={`inline-flex items-center justify-center min-w-[2.5rem] px-2 py-1 rounded-lg text-xs font-bold border tabular-nums ${scoreStyles(score)}`}
    >
      {score}
    </span>
  );
};

export const RatingDisplay: React.FC<{
  rating: number | null | undefined;
  reviewCount: number | null | undefined;
}> = ({ rating, reviewCount }) => {
  if (!reviewCount) {
    return <span className="text-xs text-slate-400 italic">No reviews</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 text-sm text-slate-700 tabular-nums">
      <Star size={13} className="text-amber-400 fill-amber-400 shrink-0" />
      {rating !== null && rating !== undefined ? rating.toFixed(1) : '-'}
      <span className="text-xs text-slate-400">({reviewCount})</span>
    </span>
  );
};
