import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money } from '../finance';
import { useFamily } from '../useFamily';
import type { Scope } from '../family';
import ScopeSelector from './ScopeSelector';

interface Budget {
    id: string;
    category_id: string;
    limit: number;
    period: string;
    // Spent in the current month (MONTHLY) or year (YEARLY), and as a percentage of the limit
    spent: number;
    percentage: number;
}

interface Category {
    id: string;
    name: string;
    type: string;
}

interface BudgetWithCategory extends Budget {
    category: Category;
}

// Budgets of a scope with what was spent in the current period; the server calculates it (Swiss time)
async function loadBudgetsWithSpending(scope: Scope): Promise<BudgetWithCategory[]> {
    const [budgetsRes, categoriesRes] = await Promise.all([
        api.get('/api/v1/budgets', { params: scope.budgetOwnerId ? { user_id: scope.budgetOwnerId } : {} }),
        api.get('/api/v1/categories')
    ]);
    const categories: Category[] = categoriesRes.data;
    return budgetsRes.data.map((budget: Budget) => ({
        ...budget,
        category: categories.find(c => c.id === budget.category_id)
    }));
}

export default function BudgetManager() {
    const { t } = useTranslation();
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
                setError(errorMessage(error, t('budgets.loadFailed')));
            });
    }, [activeScope, reloadKey, t]);

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
            setError(errorMessage(error, t('budgets.createFailed')));
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
            setError(errorMessage(error, t('budgets.updateFailed')));
        }
    };

    const handleDeleteBudget = async (budget: BudgetWithCategory) => {
        if (!confirm(t('budgets.confirmDelete', { category: budget.category?.name ?? t('budgets.thisCategory') }))) return;

        try {
            await api.delete(`/api/v1/budgets/${budget.id}`);
            reloadBudgets();
        } catch (error) {
            console.error('Failed to delete budget', error);
            setError(errorMessage(error, t('budgets.deleteFailed')));
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
                <h2 className="text-2xl font-bold">{t('budgets.title')}</h2>
                <div className="flex items-center gap-3">
                    <ScopeSelector scopes={scopes} value={activeScope?.key ?? ''} onChange={setScopeKey} />
                    {canManage && (
                    <button
                        onClick={() => setShowAddBudget(!showAddBudget)}
                        className="btn-primary text-sm"
                    >
                        {t('budgets.add')}
                    </button>
                    )}
                </div>
            </div>

            {!canManage && activeScope && (
                <p className="mb-4 text-sm text-slate-400">
                    {t('budgets.viewing', { scope: activeScope.label })}
                </p>
            )}

            {error && (
                <div className="mb-4 p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label={t('common.dismissError')}>✕</button>
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
                        <option value="">{t('budgets.selectCategory')}</option>
                        {categories.map(cat => (
                            <option key={cat.id} value={cat.id}>{cat.name}</option>
                        ))}
                    </select>
                    <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        placeholder={t('budgets.limitPlaceholder')}
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
                        <option value="MONTHLY">{t('budgets.monthly')}</option>
                        <option value="YEARLY">{t('budgets.yearly')}</option>
                    </select>
                    <button type="submit" className="btn-primary w-full">{t('budgets.set')}</button>
                </form>
            )}

            <div className="space-y-4">
                {budgets.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('budgets.none')}</p>
                ) : (
                    budgets.map(budget => (
                        <div key={budget.id} className="p-4 bg-slate-800/30 rounded-lg">
                            <div className="flex justify-between items-center mb-2">
                                <div>
                                    <h3 className="font-semibold text-lg">{budget.category?.name}</h3>
                                    <p className="text-sm text-slate-400">{budget.period === 'YEARLY' ? t('budgets.thisYear') : t('budgets.thisMonth')}</p>
                                </div>
                                <div className="text-right">
                                    <p className={`text-2xl font-bold ${getProgressTextColor(budget.percentage)}`}>
                                        {money(budget.spent)} / {money(budget.limit)}
                                    </p>
                                    <p className="text-sm text-slate-400">
                                        {budget.percentage.toFixed(1)}%
                                        {canManage && <button
                                            onClick={() => setEditingBudget({ id: budget.id, limit: budget.limit.toString(), period: budget.period })}
                                            className="ml-3 text-slate-500 hover:text-blue-400 transition-colors"
                                            title={t('budgets.editTitle')}
                                        >
                                            {t('common.edit')}
                                        </button>}
                                        {canManage && <button
                                            onClick={() => handleDeleteBudget(budget)}
                                            className="ml-3 text-slate-500 hover:text-red-400 transition-colors"
                                            title={t('budgets.deleteTitle')}
                                        >
                                            {t('common.delete')}
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
                                        aria-label={t('budgets.limit')}
                                        required
                                    />
                                    <select
                                        value={editingBudget.period}
                                        onChange={(e) => setEditingBudget({ ...editingBudget, period: e.target.value })}
                                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        aria-label={t('budgets.period')}
                                    >
                                        <option value="MONTHLY">{t('budgets.monthly')}</option>
                                        <option value="YEARLY">{t('budgets.yearly')}</option>
                                    </select>
                                    <button type="submit" className="btn-primary text-sm">{t('common.save')}</button>
                                    <button type="button" onClick={() => setEditingBudget(null)} className="px-3 text-sm text-slate-400 hover:text-white">
                                        {t('common.cancel')}
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
                                    {t('budgets.exceeded', { amount: money(budget.spent - budget.limit) })}
                                </div>
                            )}
                            {budget.percentage >= 80 && budget.percentage < 100 && (
                                <div className="mt-2 p-2 bg-yellow-500/20 border border-yellow-500/50 rounded text-yellow-400 text-sm">
                                    {t('budgets.warning', { percent: budget.percentage.toFixed(1) })}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
