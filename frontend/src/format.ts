import i18n from './i18n';

// Dates in the current language: 16.10.2026 / 16 Oct 2026, Oktober 2026 / October 2026
const locale = () => (i18n.language === 'de' ? 'de-CH' : 'en-GB');

// "2026-10" means the month; the 15th at noon keeps it in that month in every time zone
const toDate = (value: string | Date) =>
    value instanceof Date ? value : new Date(/^\d{4}-\d{2}$/.test(value) ? `${value}-15T12:00:00` : value);

export const formatDate = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), i18n.language === 'de'
        ? { day: '2-digit', month: '2-digit', year: 'numeric' }
        : { day: 'numeric', month: 'short', year: 'numeric' });

export const formatMonth = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), { month: 'long', year: 'numeric' });
