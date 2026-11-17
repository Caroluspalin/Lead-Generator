// Ostosignaalit. Rajat vastaavat backendin app/utils/signals.py:tä.
export const SLOW_LCP_SECONDS = 4;
export const FAST_LCP_SECONDS = 2.5;
export const OLD_SITE_MIN_AGE_YEARS = 3;
export const FEW_REVIEWS_BELOW = 10;

export type SignalFilter = 'slow' | 'old' | 'few';

export interface SignalInput {
  review_count?: number | null;
  pagespeed_lcp_s?: number | null;
  site_copyright_year?: number | null;
}

export interface SignalBadge {
  key: string;
  label: string;
  title: string;
  tone: 'warn' | 'good' | 'info';
}

export const isFewReviews = (reviewCount: number | null | undefined): boolean =>
  (reviewCount ?? 0) < FEW_REVIEWS_BELOW;

export const isSlow = (lcp: number | null | undefined): boolean =>
  lcp !== null && lcp !== undefined && lcp > SLOW_LCP_SECONDS;

export const isOldSite = (year: number | null | undefined): boolean =>
  year !== null && year !== undefined && new Date().getFullYear() - year >= OLD_SITE_MIN_AGE_YEARS;

export const matchesSignalFilters = (lead: SignalInput, filters: SignalFilter[]): boolean =>
  filters.every((f) =>
    f === 'slow' ? isSlow(lead.pagespeed_lcp_s) : f === 'old' ? isOldSite(lead.site_copyright_year) : isFewReviews(lead.review_count),
  );

// Vain mitatut tai sivulta luetut arvot: ei mittausta = ei nopeusmerkkiä
export const signalBadges = (lead: SignalInput, opts: { fewReviews?: boolean } = {}): SignalBadge[] => {
  const badges: SignalBadge[] = [];
  const lcp = lead.pagespeed_lcp_s;
  if (lcp !== null && lcp !== undefined) {
    const label = lcp.toFixed(1);
    if (lcp > SLOW_LCP_SECONDS) {
      badges.push({ key: 'slow', label: `Slow ${label} s`, title: 'Mobile largest contentful paint, measured with Google PageSpeed Insights', tone: 'warn' });
    } else if (lcp < FAST_LCP_SECONDS) {
      badges.push({ key: 'fast', label: `Fast ${label} s`, title: 'Mobile largest contentful paint, measured with Google PageSpeed Insights', tone: 'good' });
    }
  }
  if (isOldSite(lead.site_copyright_year)) {
    badges.push({ key: 'old', label: `Site from ${lead.site_copyright_year}`, title: 'Latest © year found on the website. The site may be newer or older than this.', tone: 'warn' });
  }
  if (opts.fewReviews !== false && isFewReviews(lead.review_count)) {
    badges.push({ key: 'few', label: 'Few reviews', title: `Fewer than ${FEW_REVIEWS_BELOW} Google reviews. May be a new business, but the review count alone does not tell.`, tone: 'info' });
  }
  return badges;
};
