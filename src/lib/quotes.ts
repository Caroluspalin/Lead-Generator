import type { QuoteLine, QuoteStatus } from '../types/agency';

const cents = new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' });

export const formatCents = (value: number): string => cents.format(value / 100);

export const formatVatRate = (bp: number): string => `${(bp / 100).toLocaleString('fi-FI', { maximumFractionDigits: 2 })} %`;

// "12,50" / "12.5" -> 1250. Ei liukulukuja: null jos muoto ei kelpaa
export function parseDecimalToHundredths(input: string): number | null {
  const match = /^(\d{1,9})(?:[.,](\d{1,2}))?$/.exec(input.trim());
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'));
}

export const hundredthsToInput = (value: number): string => {
  const whole = Math.floor(value / 100);
  const rest = value % 100;
  return rest === 0 ? String(whole) : `${whole},${String(rest).padStart(2, '0').replace(/0$/, '')}`;
};

// Sama pyöristys kuin backendin quotes.py: alv rivi kerrallaan, puolet ylöspäin
export function quoteTotals(lines: Pick<QuoteLine, 'unit_price_cents' | 'quantity' | 'vat_rate_bp'>[]) {
  let net = 0;
  let vat = 0;
  for (const line of lines) {
    const lineNet = line.unit_price_cents * line.quantity;
    net += lineNet;
    vat += Math.floor((lineNet * line.vat_rate_bp + 5000) / 10000);
  }
  return { net, vat, gross: net + vat };
}

// Kortin tila: lähetetty tarjous, jonka asiakas on avannut, näkyy Opened-tilana
export function quoteStatusLabel(status: QuoteStatus | null | undefined, openCount: number | undefined): string | null {
  if (!status) return null;
  if (status === 'draft') return 'Draft';
  if (status === 'accepted') return 'Accepted';
  if (status === 'superseded') return 'Replaced';
  return openCount ? 'Opened' : 'Sent';
}
