const eur = new Intl.NumberFormat('fi-FI', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
});

export const formatEur = (value: number): string => eur.format(value);
