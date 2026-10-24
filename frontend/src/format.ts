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

// 14:05 in both languages
export const formatTime = (value: string | Date) =>
    toDate(value).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' });

export const formatMonth = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), { month: 'long', year: 'numeric' });

// Chart labels: "16. Okt." / "16 Oct", and "Okt." / "Oct"
export const formatDayShort = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), { day: 'numeric', month: 'short' });

export const formatMonthShort = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), { month: 'short' });

// January … December (Januar … Dezember)
export const monthNames = () =>
    Array.from({ length: 12 }, (_, i) => new Date(2026, i, 15).toLocaleDateString(locale(), { month: 'long' }));
