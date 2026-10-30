import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { money } from '../finance';
import { formatDate, formatMonth } from '../format';

interface Costs {
    month: string;
    month_total: number;
    year_total: number;
    by_category: { category: string; amount: number }[];
    bookings: { date: string; description: string; category: string; amount: number }[];
}

const thisMonth = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

// A child without Jugendlohn: what they cost, read-only (spec 2026-10-30). Their parents book it; they look.
export default function ChildCosts() {
    const { t } = useTranslation();
    const { user, logout } = useAuth();
    const [month, setMonth] = useState(thisMonth);
    const [costs, setCosts] = useState<Costs | null>(null);
    const [error, setError] = useState('');

    useEffect(() => {
        api.get<Costs>('/api/v1/my-costs', { params: { month } })
            .then(res => { setCosts(res.data); setError(''); })
            .catch(err => setError(errorMessage(err, t('childCosts.failed'))));
    }, [month, t]);

    const largest = costs?.by_category[0]?.amount ?? 0;

    return (
        <div className="min-h-screen p-3 sm:p-6 space-y-4">
            <div className="glass-card p-4 sm:p-6 flex justify-between items-center gap-3">
                <div className="min-w-0">
                    <h1 className="text-2xl font-bold">{t('childCosts.title')}</h1>
                    <p className="text-slate-400 mt-1">{t('childCosts.hello', { name: user?.username })}</p>
                </div>
                <button onClick={() => void logout()} className="btn-primary">{t('dashboard.logout')}</button>
            </div>

            <div className="glass-card p-4 sm:p-6 space-y-4">
                <label className="flex flex-col gap-1.5 text-sm font-semibold text-slate-300 max-w-xs">
                    {t('childCosts.month')}
                    <input type="month" value={month} max={thisMonth()} required
                        onChange={e => e.target.value && setMonth(e.target.value)}
                        className="p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white" />
                </label>
                {error && <p role="alert" className="text-red-300">{error}</p>}
                {costs && (
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="p-4 bg-slate-800/30 rounded-lg">
                            <p className="text-sm text-slate-400">{t('childCosts.monthTotal', { month: formatMonth(costs.month) })}</p>
                            <p className="text-3xl font-bold">{money(costs.month_total)}</p>
                        </div>
                        <div className="p-4 bg-slate-800/30 rounded-lg">
                            <p className="text-sm text-slate-400">{t('childCosts.yearTotal', { year: costs.month.slice(0, 4) })}</p>
                            <p className="text-3xl font-bold">{money(costs.year_total)}</p>
                        </div>
                    </div>
                )}
            </div>

            {costs && costs.by_category.length > 0 && (
                <section className="glass-card p-4 sm:p-6" aria-labelledby="child-categories">
                    <h2 id="child-categories" className="text-lg font-semibold mb-3">{t('childCosts.byCategory')}</h2>
                    <ul className="space-y-2">
                        {costs.by_category.map(row => (
                            <li key={row.category}>
                                <div className="flex justify-between gap-3 text-sm">
                                    <span>{row.category}</span>
                                    <span>{money(row.amount)}</span>
                                </div>
                                <div className="h-2 mt-1 rounded bg-slate-800/60" aria-hidden="true">
                                    <div className="h-2 rounded bg-cyan-400"
                                        style={{ width: `${largest > 0 ? Math.max(0, (row.amount / largest) * 100) : 0}%` }} />
                                </div>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {costs && (
                <section className="glass-card p-4 sm:p-6" aria-labelledby="child-bookings">
                    <h2 id="child-bookings" className="text-lg font-semibold mb-3">{t('childCosts.bookings')}</h2>
                    {costs.bookings.length === 0
                        ? <p className="text-slate-400">{t('childCosts.none')}</p>
                        : (
                            <ul className="divide-y divide-white/5">
                                {costs.bookings.map((row, index) => (
                                    <li key={`${row.date}-${index}`} className="flex justify-between gap-3 py-2">
                                        <div className="min-w-0">
                                            <p className="break-words">{row.description || t('common.noDescription')}</p>
                                            <p className="text-sm text-slate-400">{formatDate(row.date)} · {row.category}</p>
                                        </div>
                                        <span className="whitespace-nowrap">{money(row.amount)}</span>
                                    </li>
                                ))}
                            </ul>
                        )}
                </section>
            )}
        </div>
    );
}
