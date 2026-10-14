import { useState, useEffect } from 'react';
import api, { errorMessage, fetchTransactionsForUsers } from '../api';
import { useFamily } from '../useFamily';
import type { Scope } from '../family';
import ScopeSelector from './ScopeSelector';

interface Budget {
    id: string;
    category_id: string;
    limit: number;
    period: string;
}

interface Category {
    id: string;
    name: string;
    type: string;
}

interface Transaction {
    amount: number;
    date: string;
    category_id: string;
}

interface BudgetWithCategory extends Budget {
    category: Category;
    spent: number;
    percentage: number;
}

// Budgets of a scope, with what was spent in the current period (this month or this year, local time)
async function loadBudgetsWithSpending(scope: Scope): Promise<BudgetWithCategory[]> {
    const [budgetsRes, categoriesRes, transactions] = await Promise.all([
        api.get('/api/v1/budgets', { params: scope.budgetOwnerId ? { user_id: scope.budgetOwnerId } : {} }),
        api.get('/api/v1/categories'),
        // Only the scope's accounts count
        fetchTransactionsForUsers<Transaction>(scope.userIds)
    ]);
    const categories: Category[] = categoriesRes.data;

    const now = new Date();
    const isInPeriod = (date: string, period: string) => {
        const d = new Date(date);
        return d.getFullYear() === now.getFullYear() && (period === 'YEARLY' || d.getMonth() === now.getMonth());
    };

    return budgetsRes.data.map((budget: Budget) => {
        const category = categories.find(c => c.id === budget.category_id);
        const spent = Math.abs(transactions
            .filter(t => t.category_id === budget.category_id && t.amount < 0 && isInPeriod(t.date, budget.period))
            .reduce((sum, t) => sum + t.amount, 0));

        return {
            ...budget,
            category,
            spent,
            percentage: (spent / budget.limit) * 100
        };
    });
}

export default function BudgetManager() {
    const { scopes } = useFamily();
    const [scopeKey, setScopeKey] = useState('');
    const [budgets, setBudgets] = useState<BudgetWithCategory[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [showAddBudget, setShowAddBudget] = useState(false);
    const [error, setError] = useState('');
    // Budget being edited (inline form below it)
    const [editingBudget, setEditingBudget] = useState<{ id: string; limit: string; period: string } | null>(null);
    const [newBudget, setNewBudget] = useState({
        category_id: '',
        limit: '',
        period: 'MONTHLY'
    });

    const activeScope = scopes.find(s => s.key === scopeKey) ?? scopes[0];
    // Own budgets, or someone who shared with "view and manage"; everything else is read only
    const canManage = !!activeScope && activeScope.access !== 'VIEW';

    // Bumped to load the budgets again after a change
    const [reloadKey, setReloadKey] = useState(0);
    const reloadBudgets = () => setReloadKey(k => k + 1);

    useEffect(() => {
        api.get('/api/v1/categories')
            .then(response => setCategories(response.data.filter((c: Category) => c.type === 'EXPENSE')))
            .catch(error => console.error('Failed to load categories', error));
    }, []);

    useEffect(() => {
        if (!activeScope) return;
        loadBudgetsWithSpending(activeScope)
            .then(setBudgets)
            .catch(error => {
                console.error('Failed to load budgets', error);
                setError(errorMessage(error, 'Failed to load budgets'));
            });
    }, [activeScope, reloadKey]);

    const handleAddBudget = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/budgets', {
                category_id: newBudget.category_id,
                limit: parseFloat(newBudget.limit),
                period: newBudget.period,
                user_id: activeScope?.budgetOwnerId
            });
            setNewBudget({ category_id: '', limit: '', period: 'MONTHLY' });
            setShowAddBudget(false);
            reloadBudgets();
        } catch (error) {
            console.error('Failed to create budget', error);
            setError(errorMessage(error, 'Failed to create budget'));
        }
    };

    const handleSaveBudget = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingBudget) return;

        try {
            await api.put(`/api/v1/budgets/${editingBudget.id}`, {
                limit: parseFloat(editingBudget.limit),
                period: editingBudget.period
            });
            setEditingBudget(null);
            reloadBudgets();
        } catch (error) {
            console.error('Failed to update budget', error);
            setError(errorMessage(error, 'Failed to update budget'));
        }
    };

    const handleDeleteBudget = async (budget: BudgetWithCategory) => {
        if (!confirm(`Delete the budget limit for ${budget.category?.name ?? 'this category'}?`)) return;

        try {
            await api.delete(`/api/v1/budgets/${budget.id}`);
            reloadBudgets();
        } catch (error) {
            console.error('Failed to delete budget', error);
            setError(errorMessage(error, 'Failed to delete budget'));
        }
    };

    const getProgressColor = (percentage: number) => {
        if (percentage >= 100) return 'bg-red-500';
        if (percentage >= 80) return 'bg-yellow-500';
        return 'bg-emerald-500';
    };

    const getProgressTextColor = (percentage: number) => {
        if (percentage >= 100) return 'text-red-400';
        if (percentage >= 80) return 'text-yellow-400';
        return 'text-emerald-400';
    };

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold">Budget Limits</h2>
                <div className="flex items-center gap-3">
                    <ScopeSelector scopes={scopes} value={activeScope?.key ?? ''} onChange={setScopeKey} />
                    {canManage && (
                    <button
                        onClick={() => setShowAddBudget(!showAddBudget)}
                        className="btn-primary text-sm"
                    >
                        + Set Budget Limit
                    </button>
                    )}
                </div>
            </div>

            {!canManage && activeScope && (
                <p className="mb-4 text-sm text-slate-400">
                    Viewing {activeScope.label} (read only).
                </p>
            )}

            {error && (
                <div className="mb-4 p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label="Dismiss error">✕</button>
                </div>
            )}

            {showAddBudget && canManage && (
                <form onSubmit={handleAddBudget} className="mb-6 p-4 bg-slate-800/30 rounded-lg">
                    <select
                        value={newBudget.category_id}
                        onChange={(e) => setNewBudget({ ...newBudget, category_id: e.target.value })}
                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        required
                    >
                        <option value="">Select Category</option>
                        {categories.map(cat => (
                            <option key={cat.id} value={cat.id}>{cat.name}</option>
                        ))}
                    </select>
                    <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        placeholder="Budget Limit"
                        value={newBudget.limit}
                        onChange={(e) => setNewBudget({ ...newBudget, limit: e.target.value })}
                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        required
                    />
                    <select
                        value={newBudget.period}
                        onChange={(e) => setNewBudget({ ...newBudget, period: e.target.value })}
                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                    >
                        <option value="MONTHLY">Monthly</option>
                        <option value="YEARLY">Yearly</option>
                    </select>
                    <button type="submit" className="btn-primary w-full">Set Budget</button>
                </form>
            )}

            <div className="space-y-4">
                {budgets.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">No budget limits set</p>
                ) : (
                    budgets.map(budget => (
                        <div key={budget.id} className="p-4 bg-slate-800/30 rounded-lg">
                            <div className="flex justify-between items-center mb-2">
                                <div>
                                    <h3 className="font-semibold text-lg">{budget.category?.name}</h3>
                                    <p className="text-sm text-slate-400">{budget.period === 'YEARLY' ? 'This year' : 'This month'}</p>
                                </div>
                                <div className="text-right">
                                    <p className={`text-2xl font-bold ${getProgressTextColor(budget.percentage)}`}>
                                        ${budget.spent.toFixed(2)} / ${budget.limit.toFixed(2)}
                                    </p>
                                    <p className="text-sm text-slate-400">
                                        {budget.percentage.toFixed(1)}%
                                        {canManage && <button
                                            onClick={() => setEditingBudget({ id: budget.id, limit: budget.limit.toString(), period: budget.period })}
                                            className="ml-3 text-slate-500 hover:text-blue-400 transition-colors"
                                            title="Edit budget limit"
                                        >
                                            Edit
                                        </button>}
                                        {canManage && <button
                                            onClick={() => handleDeleteBudget(budget)}
                                            className="ml-3 text-slate-500 hover:text-red-400 transition-colors"
                                            title="Delete budget limit"
                                        >
                                            Delete
                                        </button>}
                                    </p>
                                </div>
                            </div>

                            {editingBudget?.id === budget.id && (
                                <form onSubmit={handleSaveBudget} className="mb-3 flex gap-2">
                                    <input
                                        type="number"
                                        step="0.01"
                                        min="0.01"
                                        value={editingBudget.limit}
                                        onChange={(e) => setEditingBudget({ ...editingBudget, limit: e.target.value })}
                                        className="flex-1 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        aria-label="Budget limit"
                                        required
                                    />
                                    <select
                                        value={editingBudget.period}
                                        onChange={(e) => setEditingBudget({ ...editingBudget, period: e.target.value })}
                                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        aria-label="Budget period"
                                    >
                                        <option value="MONTHLY">Monthly</option>
                                        <option value="YEARLY">Yearly</option>
                                    </select>
                                    <button type="submit" className="btn-primary text-sm">Save</button>
                                    <button type="button" onClick={() => setEditingBudget(null)} className="px-3 text-sm text-slate-400 hover:text-white">
                                        Cancel
                                    </button>
                                </form>
                            )}

                            <div className="w-full bg-slate-700 rounded-full h-3 overflow-hidden">
                                <div
                                    className={`h-full ${getProgressColor(budget.percentage)} transition-all duration-300`}
                                    style={{ width: `${Math.min(budget.percentage, 100)}%` }}
                                />
                            </div>

                            {budget.percentage >= 100 && (
                                <div className="mt-2 p-2 bg-red-500/20 border border-red-500/50 rounded text-red-400 text-sm">
                                    ⚠️ Budget exceeded! You've spent ${(budget.spent - budget.limit).toFixed(2)} over the limit.
                                </div>
                            )}
                            {budget.percentage >= 80 && budget.percentage < 100 && (
                                <div className="mt-2 p-2 bg-yellow-500/20 border border-yellow-500/50 rounded text-yellow-400 text-sm">
                                    ⚠️ Warning: You've used {budget.percentage.toFixed(1)}% of your budget.
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
