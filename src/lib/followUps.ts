import type { FollowUpSequenceStatus } from '../types/agency';

// Backend palauttaa UTC-ajan ilman päätettä SQLitessä
export function parseUtc(iso: string): Date {
  return new Date(/(?:Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

// "pe 20.11." (suomalainen päivämuoto, kuten kortin muut ajat)
export function formatFollowUpDay(iso: string): string {
  const date = parseUtc(iso);
  const weekday = date.toLocaleDateString('fi-FI', { weekday: 'short' });
  return `${weekday} ${date.getDate()}.${date.getMonth() + 1}.`;
}

export function followUpStatusLabel(status: FollowUpSequenceStatus | null | undefined, nextAt?: string | null): string | null {
  switch (status) {
    case 'draft':
      return 'Follow-ups drafted, not approved';
    case 'active':
      return nextAt ? `Next follow-up ${formatFollowUpDay(nextAt)}` : 'Follow-ups approved, waiting for first email';
    case 'replied':
      return 'Replied';
    case 'stopped':
      return 'Follow-ups stopped';
    case 'completed':
      return 'Follow-ups sent';
    default:
      return null;
  }
}
