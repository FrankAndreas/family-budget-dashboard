import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import api from '../api';
import { money } from '../finance';
import { useFamily } from '../useFamily';
import ScopeSelector from './ScopeSelector';
import { formatDayShort, formatMonthShort } from '../format';

interface Amounts { income: number; expenses: number }

// Calculated by the server for one scope and range, in Swiss time (GET /reports/summary)
interface Summary extends Amounts {
    by_category: { category_id: string; name: string; amount: number }[];
    by_child: { member_id: string; name: string; amount: number }[];
    // Receipt items (issue #56): per tag (overlapping: an item counts in each of its tags) and per person
    // set_aside: per month, for the investments with the tag
    by_tag: { tag_id: string; name: string; icon?: string | null; amount: number; set_aside: number }[];
    by_person: { person_id: string; name: string; amount: number }[];
    // The last 6 months ("2026-10") and every day of the current month ("2026-10-15")
    months: (Amounts & { month: string })[];
    days: (Amounts & { date: string })[];
}

type TimeRange = 'month' | '3months' | 'year' | 'all';

// Labels: analytics.ranges.<range> in the locale files
const TIME_RANGES: TimeRange[] = ['month', '3months', 'year', 'all'];

export default function Analytics() {
    const { t } = useTranslation();
    const [summary, setSummary] = useState<Summary | null>(null);
    const [timeRange, setTimeRange] = useState<TimeRange>('month');
    const { users, scopes } = useFamily();
    const [scopeKey, setScopeKey] = useState('');
    const activeScope = scopes.find(s => s.key === scopeKey) ?? scopes[0];
    // Whose money: a scope is one person's accounts
    const ownerId = activeScope?.userIds[0];

    useEffect(() => {
        if (!ownerId) return;
        api.get('/api/v1/reports/summary', { params: { user_id: ownerId, range: timeRange } })
            .then(res => setSummary(res.data))
            .catch(error => console.error('Failed to load analytics data', error));
    }, [ownerId, timeRange]);

    const COLORS = ['#22d3ee', '#e879f9', '#818cf8', '#34d399', '#f87171', '#fbbf24', '#fb923c'];

    const dailyData = (summary?.days ?? []).map(d => ({
        date: formatDayShort(d.date),
        income: d.income,
        expenses: d.expenses,
        net: d.income - d.expenses
    }));
    const monthlyData = (summary?.months ?? []).map(m => ({
        month: formatMonthShort(m.month),
        income: m.income,
        expenses: m.expenses,
        savings: m.income - m.expenses
    }));
    const categoryData = (summary?.by_category ?? []).map(c => ({ name: c.name, value: c.amount }));

    const totalIncome = summary?.income ?? 0;
    const totalExpenses = summary?.expenses ?? 0;
    const rangeLabel = t(`analytics.ranges.${timeRange}`);
    const netSavings = totalIncome - totalExpenses;

    // Expenses tagged with a dependent child, per child
    const childCosts = (summary?.by_child ?? []).map(child => ({ name: child.name, value: child.amount }));

    return (
        <div className="space-y-6">
            {/* Scope and Time Range */}
            <div className="flex justify-end gap-3">
                <ScopeSelector scopes={scopes} value={activeScope?.key ?? ''} onChange={setScopeKey} />
                <select
                    value={timeRange}
                    onChange={(e) => setTimeRange(e.target.value as TimeRange)}
                    className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                    aria-label={t('analytics.timeRange')}
                >
                    {TIME_RANGES.map(range => (
                        <option key={range} value={range}>{t(`analytics.ranges.${range}`)}</option>
                    ))}
                </select>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="glass-card p-6">
                    <h3 className="text-emerald-400 text-sm font-semibold mb-2">{t('analytics.income', { range: rangeLabel })}</h3>
                    <p className="text-3xl font-bold">{money(totalIncome)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-red-400 text-sm font-semibold mb-2">{t('analytics.expenses', { range: rangeLabel })}</h3>
                    <p className="text-3xl font-bold">{money(totalExpenses)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className={`${netSavings >= 0 ? 'text-sky-400' : 'text-red-400'} text-sm font-semibold mb-2`}>
                        {t(netSavings >= 0 ? 'analytics.netSavings' : 'analytics.netDeficit', { range: rangeLabel })}
                    </h3>
                    <p className="text-3xl font-bold">{money(Math.abs(netSavings))}</p>
                </div>
            </div>

            {/* Monthly Comparison */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">{t('analytics.comparison')}</h2>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={monthlyData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="month" stroke="#94a3b8" />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip
                            formatter={(value) => money(Number(value))}
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f8fafc' }}
                        />
                        <Legend />
                        <Bar dataKey="income" fill="#34d399" name={t('analytics.incomeSeries')} />
                        <Bar dataKey="expenses" fill="#f87171" name={t('analytics.expensesSeries')} />
                        <Bar dataKey="savings" fill="#22d3ee" name={t('analytics.savingsSeries')} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Daily Trend */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">{t('analytics.dailyTrend')}</h2>
                <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={dailyData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="date" stroke="#94a3b8" />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip
                            formatter={(value) => money(Number(value))}
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f8fafc' }}
                        />
                        <Legend />
                        <Line type="monotone" dataKey="income" stroke="#34d399" strokeWidth={2} name={t('analytics.incomeSeries')} />
                        <Line type="monotone" dataKey="expenses" stroke="#f87171" strokeWidth={2} name={t('analytics.expensesSeries')} />
                        <Line type="monotone" dataKey="net" stroke="#22d3ee" strokeWidth={2} name={t('analytics.netSeries')} />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* Costs per dependent child */}
            {users.find(u => u.id === activeScope?.userIds[0])?.role === 'PARENT' && childCosts.length > 0 && (
                <div className="glass-card p-6">
                    <h2 className="text-xl font-bold mb-1">{t('analytics.costsPerChild', { range: rangeLabel })}</h2>
                    <p className="text-sm text-slate-400 mb-4">{t('analytics.costsPerChildIntro')}</p>
                    <div className="space-y-2">
                        {childCosts.map(child => (
                            <div key={child.name} className="flex items-center justify-between p-2 bg-slate-800/30 rounded">
                                <span>{child.name}</span>
                                <span className="font-bold">{money(child.value)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Spending by tag (receipt items, bookings for an investment with the tag) and what its investments set aside; a list without a sum, since an item with several tags counts in each */}
            {(summary?.by_tag.length ?? 0) > 0 && (
                <div className="glass-card p-6">
                    <h2 className="text-xl font-bold mb-1">{t('analytics.byTag', { range: rangeLabel })}</h2>
                    <p className="text-sm text-slate-400 mb-4">{t('analytics.tagsOverlap')}</p>
                    <div className="space-y-2">
                        {summary!.by_tag.map(tag => (
                            <div key={tag.tag_id} data-tag-row className="flex items-center justify-between gap-3 p-2 bg-slate-800/30 rounded">
                                <span>{tag.icon ? `${tag.icon} ` : ''}{tag.name}</span>
                                <span className="text-right">
                                    <span className="font-bold">{money(tag.amount)}</span>
                                    {tag.set_aside > 0 && (
                                        <span className="block text-xs text-slate-400">{t('analytics.setAside', { amount: money(tag.set_aside) })}</span>
                                    )}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {(summary?.by_person.length ?? 0) > 0 && (
                <div className="glass-card p-6">
                    <h2 className="text-xl font-bold mb-1">{t('analytics.byPerson', { range: rangeLabel })}</h2>
                    <p className="text-sm text-slate-400 mb-4">{t('analytics.byPersonIntro')}</p>
                    <div className="space-y-2">
                        {summary!.by_person.map(person => (
                            <div key={person.person_id} className="flex items-center justify-between p-2 bg-slate-800/30 rounded">
                                <span>{person.name}</span>
                                <span className="font-bold">{money(person.amount)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Category Breakdown */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">{t('analytics.byCategory', { range: rangeLabel })}</h2>
                {categoryData.length > 0 ? (
                    <div className="flex flex-col md:flex-row items-center gap-8">
                        <ResponsiveContainer width="100%" height={300}>
                            <PieChart>
                                <Pie
                                    data={categoryData}
                                    cx="50%"
                                    cy="50%"
                                    labelLine={false}
                                    label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                                    outerRadius={100}
                                    fill="#8884d8"
                                    dataKey="value"
                                >
                                    {categoryData.map((_, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip
                            formatter={(value) => money(Number(value))}
                                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                                />
                            </PieChart>
                        </ResponsiveContainer>
                        <div className="flex-1 space-y-2">
                            {categoryData.map((cat, index) => (
                                <div key={cat.name} className="flex items-center justify-between p-2 bg-slate-800/30 rounded">
                                    <div className="flex items-center gap-2">
                                        <div
                                            className="w-4 h-4 rounded"
                                            style={{ backgroundColor: COLORS[index % COLORS.length] }}
                                        />
                                        <span>{cat.name}</span>
                                    </div>
                                    <span className="font-bold">{money(cat.value)}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <p className="text-slate-400 text-center py-8">{t('analytics.noData')}</p>
                )}
            </div>
        </div>
    );
}
