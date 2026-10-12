import { useState, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import api, { fetchTransactionsForUsers } from '../api';
import { useFamily } from '../useFamily';
import { HOUSEHOLD_SCOPE, dependents } from '../family';
import ScopeSelector from './ScopeSelector';
import { format, startOfMonth, startOfYear, endOfMonth, eachDayOfInterval, subMonths } from 'date-fns';

interface Transaction {
    id: string;
    amount: number;
    date: string;
    category_id: string;
    member_id?: string | null;
}

interface Category {
    id: string;
    name: string;
    type: string;
}

type TimeRange = 'month' | '3months' | 'year' | 'all';

const TIME_RANGE_LABELS: Record<TimeRange, string> = {
    month: 'This Month',
    '3months': 'Last 3 Months',
    year: 'This Year',
    all: 'All Time'
};

// Start of the selected range in local time; null means no lower bound
const rangeStart = (range: TimeRange): Date | null => {
    const now = new Date();
    if (range === 'month') return startOfMonth(now);
    if (range === '3months') return startOfMonth(subMonths(now, 2));
    if (range === 'year') return startOfYear(now);
    return null;
};

export default function Analytics() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [timeRange, setTimeRange] = useState<TimeRange>('month');
    const { users, scopes } = useFamily();
    const [scopeKey, setScopeKey] = useState(HOUSEHOLD_SCOPE);
    const activeScope = scopes.find(s => s.key === scopeKey) ?? scopes[0];

    useEffect(() => {
        if (!activeScope) return;
        // Only the scope's accounts count (e.g. a child's own allowance stays out of the household)
        Promise.all([
            api.get('/api/v1/categories'),
            fetchTransactionsForUsers<Transaction>(activeScope.userIds)
        ])
            .then(([categoriesRes, scopeTransactions]) => {
                setCategories(categoriesRes.data);
                setTransactions(scopeTransactions);
            })
            .catch(error => console.error('Failed to load analytics data', error));
    }, [activeScope]);

    // Calculate daily spending trend
    const getDailyTrend = () => {
        const now = new Date();
        const start = startOfMonth(now);
        const end = endOfMonth(now);
        const days = eachDayOfInterval({ start, end });

        return days.map(day => {
            const dayStr = format(day, 'yyyy-MM-dd');
            const dayTransactions = transactions.filter(t =>
                format(new Date(t.date), 'yyyy-MM-dd') === dayStr
            );

            const income = dayTransactions
                .filter(t => t.amount > 0)
                .reduce((sum, t) => sum + t.amount, 0);

            const expenses = Math.abs(dayTransactions
                .filter(t => t.amount < 0)
                .reduce((sum, t) => sum + t.amount, 0));

            return {
                date: format(day, 'MMM dd'),
                income,
                expenses,
                net: income - expenses
            };
        });
    };

    // Transactions in the selected time range (summary cards and category breakdown)
    const start = rangeStart(timeRange);
    const rangeTransactions = start ? transactions.filter(t => new Date(t.date) >= start) : transactions;

    // Calculate spending by category
    const getCategoryBreakdown = () => {
        const categorySpending: { [key: string]: number } = {};

        rangeTransactions.forEach(t => {
            if (t.amount < 0) { // Only expenses
                const category = categories.find(c => c.id === t.category_id);
                const categoryName = category?.name || 'Unknown';
                categorySpending[categoryName] = (categorySpending[categoryName] || 0) + Math.abs(t.amount);
            }
        });

        return Object.entries(categorySpending).map(([name, value]) => ({
            name,
            value: parseFloat(value.toFixed(2))
        }));
    };

    // Calculate monthly comparison
    const getMonthlyComparison = () => {
        const months = [];
        for (let i = 5; i >= 0; i--) {
            const monthDate = subMonths(new Date(), i);
            const monthStr = format(monthDate, 'yyyy-MM');

            const monthTransactions = transactions.filter(t =>
                format(new Date(t.date), 'yyyy-MM') === monthStr
            );

            const income = monthTransactions
                .filter(t => t.amount > 0)
                .reduce((sum, t) => sum + t.amount, 0);

            const expenses = Math.abs(monthTransactions
                .filter(t => t.amount < 0)
                .reduce((sum, t) => sum + t.amount, 0));

            months.push({
                month: format(monthDate, 'MMM'),
                income,
                expenses,
                savings: income - expenses
            });
        }

        return months;
    };

    const COLORS = ['#22d3ee', '#e879f9', '#818cf8', '#34d399', '#f87171', '#fbbf24', '#fb923c'];

    const dailyData = getDailyTrend();
    const categoryData = getCategoryBreakdown();
    const monthlyData = getMonthlyComparison();

    const totalIncome = rangeTransactions.filter(t => t.amount > 0).reduce((sum, t) => sum + t.amount, 0);
    const totalExpenses = Math.abs(rangeTransactions.filter(t => t.amount < 0).reduce((sum, t) => sum + t.amount, 0));
    const rangeLabel = TIME_RANGE_LABELS[timeRange];
    const netSavings = totalIncome - totalExpenses;

    // Household expenses tagged with a dependent child, per child
    const childCosts = dependents(users)
        .map(child => ({
            name: child.username,
            value: Math.abs(rangeTransactions
                .filter(t => t.member_id === child.id && t.amount < 0)
                .reduce((sum, t) => sum + t.amount, 0))
        }))
        .filter(child => child.value > 0);

    return (
        <div className="space-y-6">
            {/* Scope and Time Range */}
            <div className="flex justify-end gap-3">
                <ScopeSelector scopes={scopes} value={activeScope?.key ?? ''} onChange={setScopeKey} />
                <select
                    value={timeRange}
                    onChange={(e) => setTimeRange(e.target.value as TimeRange)}
                    className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                    aria-label="Time range"
                >
                    {(Object.keys(TIME_RANGE_LABELS) as TimeRange[]).map(range => (
                        <option key={range} value={range}>{TIME_RANGE_LABELS[range]}</option>
                    ))}
                </select>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="glass-card p-6">
                    <h3 className="text-emerald-400 text-sm font-semibold mb-2">Income ({rangeLabel})</h3>
                    <p className="text-3xl font-bold">${totalIncome.toFixed(2)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-red-400 text-sm font-semibold mb-2">Expenses ({rangeLabel})</h3>
                    <p className="text-3xl font-bold">${totalExpenses.toFixed(2)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className={`${netSavings >= 0 ? 'text-sky-400' : 'text-red-400'} text-sm font-semibold mb-2`}>
                        Net {netSavings >= 0 ? 'Savings' : 'Deficit'} ({rangeLabel})
                    </h3>
                    <p className="text-3xl font-bold">${Math.abs(netSavings).toFixed(2)}</p>
                </div>
            </div>

            {/* Monthly Comparison */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">6-Month Comparison</h2>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={monthlyData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="month" stroke="#94a3b8" />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f8fafc' }}
                        />
                        <Legend />
                        <Bar dataKey="income" fill="#34d399" name="Income" />
                        <Bar dataKey="expenses" fill="#f87171" name="Expenses" />
                        <Bar dataKey="savings" fill="#22d3ee" name="Savings" />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Daily Trend */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">Daily Trend (This Month)</h2>
                <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={dailyData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="date" stroke="#94a3b8" />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f8fafc' }}
                        />
                        <Legend />
                        <Line type="monotone" dataKey="income" stroke="#34d399" strokeWidth={2} name="Income" />
                        <Line type="monotone" dataKey="expenses" stroke="#f87171" strokeWidth={2} name="Expenses" />
                        <Line type="monotone" dataKey="net" stroke="#22d3ee" strokeWidth={2} name="Net" />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* Costs per dependent child */}
            {activeScope?.key === HOUSEHOLD_SCOPE && childCosts.length > 0 && (
                <div className="glass-card p-6">
                    <h2 className="text-xl font-bold mb-1">Costs per Child ({rangeLabel})</h2>
                    <p className="text-sm text-slate-400 mb-4">Household expenses tagged with a child. They're included in the totals above.</p>
                    <div className="space-y-2">
                        {childCosts.map(child => (
                            <div key={child.name} className="flex items-center justify-between p-2 bg-slate-800/30 rounded">
                                <span>{child.name}</span>
                                <span className="font-bold">${child.value.toFixed(2)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Category Breakdown */}
            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">Spending by Category ({rangeLabel})</h2>
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
                                    <span className="font-bold">${cat.value.toFixed(2)}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <p className="text-slate-400 text-center py-8">No expense data available</p>
                )}
            </div>
        </div>
    );
}
