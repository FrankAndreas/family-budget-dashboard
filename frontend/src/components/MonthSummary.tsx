import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { money } from '../finance';
import { monthNames } from '../format';

interface Budget { category_id: string | null; tag_id?: string | null; limit: number; period: string; spent: number; percentage: number }

// The top of the overview: your balance, what you spent this month against your budgets, and what is left. The
// server calculates the month in Swiss time (GET /reports/summary, GET /budgets)
export default function MonthSummary({ balance, version }: { balance: number; version: number }) {
    const { t } = useTranslation();
    const [month, setMonth] = useState<{ income: number; expenses: number } | null>(null);
    const [budgets, setBudgets] = useState<Budget[]>([]);

    useEffect(() => {
        api.get('/api/v1/reports/summary', { params: { range: 'month' } })
            .then(res => setMonth({ income: res.data.income, expenses: res.data.expenses }))
            .catch(() => setMonth(null));
        api.get('/api/v1/budgets')
            .then(res => setBudgets(res.data))
            .catch(() => setBudgets([]));
    }, [version]);

    const monthly = budgets.filter(b => b.period === 'MONTHLY');
    // Category budgets don't overlap, so they add up; a tag budget can cover the same spending again
    const byCategory = monthly.filter(b => b.category_id);
    const limit = byCategory.reduce((sum, b) => sum + b.limit, 0);
    const spent = byCategory.reduce((sum, b) => sum + b.spent, 0);
    const over = monthly.filter(b => b.percentage >= 100).length;
    const left = month ? month.income - month.expenses : 0;
    // The month alone ("November"): the year is clear, and the heading stays on one line on a phone
    const name = monthNames()[new Date().getMonth()];
    const card = 'glass-card p-3 md:p-6';
    const heading = 'text-sm md:text-lg font-semibold md:mb-2';

    return (
        // On a phone the balance spans the row and the two month cards sit side by side below it
        <div data-testid="summary-cards" className="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
            <div className={`${card} col-span-2 md:col-span-1`}>
                <h3 className={`text-emerald-400 ${heading}`}>{t('accounts.myBalance')}</h3>
                <p className="text-2xl md:text-3xl font-bold">{money(balance)}</p>
            </div>
            <div className={card} data-testid="spent-this-month">
                <h3 className={`text-red-300 ${heading}`}>{t('overview.spent', { month: name })}</h3>
                <p className="text-xl md:text-3xl font-bold whitespace-nowrap">{month ? money(month.expenses) : '–'}</p>
                {limit > 0 && (
                    <>
                        <div className="mt-2 h-1.5 rounded-full bg-slate-700 overflow-hidden" aria-hidden>
                            <div className={`h-full ${spent > limit ? 'bg-red-400' : spent > limit * 0.8 ? 'bg-amber-400' : 'bg-emerald-400'}`}
                                style={{ width: `${Math.min(100, (spent / limit) * 100)}%` }} />
                        </div>
                        <p className="mt-1 text-xs md:text-sm text-slate-400">{t('overview.ofBudget', { spent: money(spent), limit: money(limit) })}</p>
                    </>
                )}
                {over > 0 && <p className="mt-1 text-xs md:text-sm text-red-400">{t('overview.overBudget', { count: over })}</p>}
            </div>
            <div className={card} data-testid="left-this-month">
                <h3 className={`${left >= 0 ? 'text-sky-400' : 'text-red-400'} ${heading}`}>
                    {t(left >= 0 ? 'overview.left' : 'overview.short', { month: name })}
                </h3>
                <p className="text-xl md:text-3xl font-bold whitespace-nowrap">{month ? money(Math.abs(left)) : '–'}</p>
                {month && <p className="mt-1 text-xs md:text-sm text-slate-400">{t('overview.income', { amount: money(month.income) })}</p>}
            </div>
        </div>
    );
}
