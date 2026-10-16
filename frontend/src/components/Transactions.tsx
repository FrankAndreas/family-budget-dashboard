import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money, type Asset, type Split } from '../finance';
import { formatDate } from '../format';
import type { Account, Category, Transaction } from '../accounts';
import type { FamilyUser } from '../family';

interface Props {
    account: Account;
    transactions: Transaction[];
    categories: Category[];
    // Own account, or shared with "view and manage"
    canEdit: boolean;
    ownerName?: string;
    // A parent's account: its expenses can be tagged with a child, shared, or linked to an investment
    isParentAccount: boolean;
    isParent: boolean;
    // Children without own allowance
    children: FamilyUser[];
    splits: Split[];
    assets: Asset[];
    // A transaction was added, changed or deleted
    onChanged: () => void;
    onError: (message: string) => void;
}

const emptyForm = { amount: '', description: '', category_id: '', member_id: '', split_id: '', asset_id: '' };
const field = 'w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// The selected account's transactions, with the form to add or edit one
export default function Transactions({
    account, transactions, categories, canEdit, ownerName, isParentAccount, isParent, children, splits, assets,
    onChanged, onError
}: Props) {
    const { t } = useTranslation();
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState(emptyForm);
    // Set while the form is editing an existing transaction instead of adding one
    const [editingId, setEditingId] = useState<string | null>(null);

    const incomeCategories = categories.filter(c => c.type === 'INCOME');
    const expenseCategories = categories.filter(c => c.type === 'EXPENSE');
    const isExpense = (categoryId: string) => expenseCategories.some(c => c.id === categoryId);
    const isTransfer = (transaction: Transaction) =>
        categories.find(c => c.id === transaction.category_id)?.type === 'TRANSFER';
    const isSettleUp = (transaction: Transaction) =>
        categories.find(c => c.id === transaction.category_id)?.system_key === 'SETTLE_UP';
    const memberName = (memberId?: string | null) => children.find(c => c.id === memberId)?.username;
    const assetName = (id?: string | null) => assets.find(a => a.id === id)?.name;
    const canTagChild = isParentAccount && children.length > 0;
    // Shared costs: a parent's expense divided with a split
    const canShare = isParent && isParentAccount && splits.length > 0 && isExpense(form.category_id);
    // Repairs, service, tyres... can be linked to an investment
    const canLinkItem = isParent && assets.length > 0 && isExpense(form.category_id);

    const closeForm = () => {
        setForm(emptyForm);
        setEditingId(null);
        setShowForm(false);
    };

    const handleEdit = (transaction: Transaction) => {
        setForm({
            amount: Math.abs(transaction.amount).toString(),
            description: transaction.description || '',
            category_id: transaction.category_id,
            member_id: transaction.member_id || '',
            split_id: transaction.split_id || '',
            asset_id: transaction.asset_id || ''
        });
        setEditingId(transaction.id);
        setShowForm(true);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const fields = {
            category_id: form.category_id,
            amount: parseFloat(form.amount),
            description: form.description,
            // null removes a tag when editing
            member_id: form.member_id || null,
            split_id: form.split_id || null,
            asset_id: form.asset_id || null
        };
        try {
            if (editingId) {
                await api.put(`/api/v1/transactions/${editingId}`, fields);
            } else {
                await api.post('/api/v1/transactions', { ...fields, account_id: account.id });
            }
            closeForm();
            onChanged();
        } catch (error) {
            console.error('Failed to save transaction', error);
            onError(errorMessage(error, t('transactions.saveFailed')));
        }
    };

    const handleDelete = async (transaction: Transaction) => {
        if (!confirm(t('transactions.confirmDelete', {
            description: transaction.description || t('transactions.noDescription'), amount: money(transaction.amount),
        }))) return;
        try {
            await api.delete(`/api/v1/transactions/${transaction.id}`);
            onChanged();
        } catch (error) {
            console.error('Failed to delete transaction', error);
            onError(errorMessage(error, t('transactions.deleteFailed')));
        }
    };

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">{t('transactions.title')}</h2>
                {canEdit && (
                    <button onClick={() => showForm ? closeForm() : setShowForm(true)} className="btn-primary text-sm">
                        {t('transactions.add')}
                    </button>
                )}
            </div>

            {!canEdit && (
                <p className="text-sm text-slate-400 mb-3">
                    {t('transactions.readOnly', { owner: ownerName ?? t('transactions.theOwner') })}
                </p>
            )}

            {showForm && canEdit && (
                <form onSubmit={handleSubmit} className="mb-4 p-4 bg-slate-800/30 rounded-lg">
                    <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        placeholder={t('transactions.amountPlaceholder')}
                        value={form.amount}
                        onChange={(e) => setForm({ ...form, amount: e.target.value })}
                        className={field}
                        required
                    />
                    <input
                        type="text"
                        placeholder={t('transactions.descriptionPlaceholder')}
                        value={form.description}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        className={field}
                    />
                    <select
                        value={form.category_id}
                        onChange={(e) => setForm({
                            ...form,
                            category_id: e.target.value,
                            // Only expenses can be shared
                            split_id: isExpense(e.target.value) ? form.split_id : '',
                            asset_id: isExpense(e.target.value) ? form.asset_id : ''
                        })}
                        className={field}
                        required
                    >
                        <option value="">{t('transactions.selectCategory')}</option>
                        <optgroup label={t('transactions.income')}>
                            {incomeCategories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                        </optgroup>
                        <optgroup label={t('transactions.expenses')}>
                            {expenseCategories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                        </optgroup>
                    </select>
                    {canTagChild && (
                        <select
                            value={form.member_id}
                            onChange={(e) => setForm({ ...form, member_id: e.target.value })}
                            className={field}
                            aria-label={t('transactions.forChild')}
                        >
                            <option value="">{t('transactions.forNoChild')}</option>
                            {children.map(child => <option key={child.id} value={child.id}>{t('transactions.forName', { name: child.username })}</option>)}
                        </select>
                    )}
                    {canShare && (
                        <select
                            value={form.split_id}
                            onChange={(e) => setForm({ ...form, split_id: e.target.value })}
                            className={field}
                            aria-label={t('transactions.shared')}
                        >
                            <option value="">{t('transactions.notShared')}</option>
                            {splits.map(split => <option key={split.id} value={split.id}>{t('transactions.sharedWith', { name: split.name })}</option>)}
                        </select>
                    )}
                    {canLinkItem && (
                        <select
                            value={form.asset_id}
                            onChange={(e) => setForm({ ...form, asset_id: e.target.value })}
                            className={field}
                            aria-label={t('transactions.forItem')}
                        >
                            <option value="">{t('transactions.forNoItem')}</option>
                            {assets.map(asset => <option key={asset.id} value={asset.id}>{t('transactions.forItemName', { name: asset.name })}</option>)}
                        </select>
                    )}
                    <div className="flex gap-2">
                        <button type="submit" className="btn-primary flex-1">
                            {editingId ? t('transactions.saveChanges') : t('transactions.addTransaction')}
                        </button>
                        {editingId && (
                            <button type="button" onClick={closeForm} className="px-4 text-slate-400 hover:text-white">
                                {t('common.cancel')}
                            </button>
                        )}
                    </div>
                </form>
            )}

            <div className="space-y-2">
                {transactions.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('transactions.none')}</p>
                ) : (
                    transactions.map(transaction => (
                        <div key={transaction.id} className="p-3 bg-slate-800/30 rounded-lg flex justify-between items-center">
                            <div>
                                <p className="font-semibold">
                                    {transaction.description || t('transactions.noDescription')}
                                    {memberName(transaction.member_id) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                                            {t('transactions.forBadge', { name: memberName(transaction.member_id) })}
                                        </span>
                                    )}
                                    {assetName(transaction.asset_id) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                                            {assetName(transaction.asset_id)}
                                        </span>
                                    )}
                                    {(transaction.split_id || transaction.split_shares) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300">
                                            {t('transactions.sharedBadge')}
                                        </span>
                                    )}
                                </p>
                                <p className="text-sm text-slate-400">{formatDate(transaction.date)}</p>
                            </div>
                            <div className="flex items-center gap-3">
                                <p className={`text-xl font-bold ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {transaction.amount >= 0 ? '+ ' : ''}{money(transaction.amount)}
                                </p>
                                {canEdit && !isTransfer(transaction) && (
                                    <button
                                        onClick={() => handleEdit(transaction)}
                                        className="text-slate-500 hover:text-blue-400 transition-colors"
                                        title={t('transactions.edit')}
                                        aria-label={t('transactions.edit')}
                                    >
                                        ✎
                                    </button>
                                )}
                                {/* Settle up is undone in the Common tab; imported transfers can be deleted here */}
                                {canEdit && !isSettleUp(transaction) && (
                                    <button
                                        onClick={() => handleDelete(transaction)}
                                        className="text-slate-500 hover:text-red-400 transition-colors"
                                        title={t('transactions.delete')}
                                        aria-label={t('transactions.delete')}
                                    >
                                        ✕
                                    </button>
                                )}
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
