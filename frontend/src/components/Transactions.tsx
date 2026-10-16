import { useState } from 'react';
import api, { errorMessage } from '../api';
import { money, type Asset, type Split } from '../finance';
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
        categories.find(c => c.id === transaction.category_id)?.name === 'Settle up';
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
            onError(errorMessage(error, 'Failed to save transaction'));
        }
    };

    const handleDelete = async (transaction: Transaction) => {
        if (!confirm(`Delete "${transaction.description || 'No description'}" (${money(transaction.amount)})?`)) return;
        try {
            await api.delete(`/api/v1/transactions/${transaction.id}`);
            onChanged();
        } catch (error) {
            console.error('Failed to delete transaction', error);
            onError(errorMessage(error, 'Failed to delete transaction'));
        }
    };

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">Transactions</h2>
                {canEdit && (
                    <button onClick={() => showForm ? closeForm() : setShowForm(true)} className="btn-primary text-sm">
                        + Add Transaction
                    </button>
                )}
            </div>

            {!canEdit && (
                <p className="text-sm text-slate-400 mb-3">
                    Read only: {ownerName ?? 'the owner'} shared this account with you to view.
                </p>
            )}

            {showForm && canEdit && (
                <form onSubmit={handleSubmit} className="mb-4 p-4 bg-slate-800/30 rounded-lg">
                    <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        placeholder="Amount (income or expense is set by the category)"
                        value={form.amount}
                        onChange={(e) => setForm({ ...form, amount: e.target.value })}
                        className={field}
                        required
                    />
                    <input
                        type="text"
                        placeholder="Description"
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
                        <option value="">Select Category</option>
                        <optgroup label="Income">
                            {incomeCategories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                        </optgroup>
                        <optgroup label="Expenses">
                            {expenseCategories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                        </optgroup>
                    </select>
                    {canTagChild && (
                        <select
                            value={form.member_id}
                            onChange={(e) => setForm({ ...form, member_id: e.target.value })}
                            className={field}
                            aria-label="For child"
                        >
                            <option value="">For: no child</option>
                            {children.map(child => <option key={child.id} value={child.id}>For: {child.username}</option>)}
                        </select>
                    )}
                    {canShare && (
                        <select
                            value={form.split_id}
                            onChange={(e) => setForm({ ...form, split_id: e.target.value })}
                            className={field}
                            aria-label="Shared"
                        >
                            <option value="">Shared: not shared</option>
                            {splits.map(split => <option key={split.id} value={split.id}>Shared: {split.name}</option>)}
                        </select>
                    )}
                    {canLinkItem && (
                        <select
                            value={form.asset_id}
                            onChange={(e) => setForm({ ...form, asset_id: e.target.value })}
                            className={field}
                            aria-label="For item"
                        >
                            <option value="">For item: none</option>
                            {assets.map(asset => <option key={asset.id} value={asset.id}>For item: {asset.name}</option>)}
                        </select>
                    )}
                    <div className="flex gap-2">
                        <button type="submit" className="btn-primary flex-1">
                            {editingId ? 'Save Changes' : 'Add Transaction'}
                        </button>
                        {editingId && (
                            <button type="button" onClick={closeForm} className="px-4 text-slate-400 hover:text-white">
                                Cancel
                            </button>
                        )}
                    </div>
                </form>
            )}

            <div className="space-y-2">
                {transactions.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">No transactions yet</p>
                ) : (
                    transactions.map(transaction => (
                        <div key={transaction.id} className="p-3 bg-slate-800/30 rounded-lg flex justify-between items-center">
                            <div>
                                <p className="font-semibold">
                                    {transaction.description || 'No description'}
                                    {memberName(transaction.member_id) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                                            for {memberName(transaction.member_id)}
                                        </span>
                                    )}
                                    {assetName(transaction.asset_id) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                                            {assetName(transaction.asset_id)}
                                        </span>
                                    )}
                                    {(transaction.split_id || transaction.split_shares) && (
                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300">
                                            shared
                                        </span>
                                    )}
                                </p>
                                <p className="text-sm text-slate-400">{new Date(transaction.date).toLocaleDateString()}</p>
                            </div>
                            <div className="flex items-center gap-3">
                                <p className={`text-xl font-bold ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {transaction.amount >= 0 ? '+ ' : ''}{money(transaction.amount)}
                                </p>
                                {canEdit && !isTransfer(transaction) && (
                                    <button
                                        onClick={() => handleEdit(transaction)}
                                        className="text-slate-500 hover:text-blue-400 transition-colors"
                                        title="Edit transaction"
                                        aria-label="Edit transaction"
                                    >
                                        ✎
                                    </button>
                                )}
                                {/* Settle up is undone in the Common tab; imported transfers can be deleted here */}
                                {canEdit && !isSettleUp(transaction) && (
                                    <button
                                        onClick={() => handleDelete(transaction)}
                                        className="text-slate-500 hover:text-red-400 transition-colors"
                                        title="Delete transaction"
                                        aria-label="Delete transaction"
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
