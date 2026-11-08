import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../../api';
import type { Account, Category, Transaction } from '../../accounts';
import type { FamilyUser } from '../../family';
import type { Asset, Split } from '../../finance';
import { localDay } from '../../format';
import { useScrollIntoView } from '../../useScrollIntoView';
import AssetLink from '../AssetLink';

interface Props {
    account: Account;
    categories: Category[];
    // The booking being edited; none: a new one
    editing: Transaction | null;
    isParent: boolean;
    // A parent's account: its expenses can be tagged with a child, shared, or linked to an investment
    isParentAccount: boolean;
    // Children without own allowance
    children: FamilyUser[];
    splits: Split[];
    assets: Asset[];
    onSaved: () => void;
    onCancel: () => void;
    onError: (message: string) => void;
}

export const field = 'w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-500 text-white';

const emptyForm = () => ({
    amount: '', description: '', category_id: '', member_id: '', split_id: '', asset_id: '', asset_purchase: false,
    // The day it happened (today unless changed) and money back in an expense category
    date: localDay(), refund: false,
});

// Adding a plain booking, or changing one (a receipt with items has its own form)
export default function BookingForm({
    account, categories, editing, isParent, isParentAccount, children, splits, assets, onSaved, onCancel, onError
}: Props) {
    const { t } = useTranslation();
    const incomeCategories = categories.filter(c => c.type === 'INCOME');
    const expenseCategories = categories.filter(c => c.type === 'EXPENSE');
    const isExpense = (categoryId: string) => expenseCategories.some(c => c.id === categoryId);
    const [form, setForm] = useState(() => editing ? {
        amount: Math.abs(editing.amount).toString(),
        description: editing.description || '',
        category_id: editing.category_id,
        member_id: editing.member_id || '',
        split_id: editing.split_id || '',
        asset_id: editing.asset_id || '',
        asset_purchase: !!editing.asset_purchase,
        date: localDay(editing.date),
        refund: isExpense(editing.category_id) && editing.amount > 0,
    } : emptyForm());
    // The day the edited booking had: only a changed day is sent, so the booking keeps its time
    const originalDay = editing ? localDay(editing.date) : null;
    const formRef = useScrollIntoView<HTMLFormElement>(editing?.id);

    const canTagChild = isParentAccount && children.length > 0;
    // Shared costs: a parent's expense divided with a split
    const canShare = isParent && isParentAccount && splits.length > 0 && isExpense(form.category_id);
    // Repairs, service, tyres... can be linked to an investment
    const canLinkItem = isParent && assets.length > 0 && isExpense(form.category_id);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const fields = {
            category_id: form.category_id,
            amount: parseFloat(form.amount),
            description: form.description,
            // null removes a tag when editing
            member_id: form.member_id || null,
            split_id: form.split_id || null,
            asset_id: form.asset_id || null,
            asset_purchase: !!form.asset_id && form.asset_purchase && !form.refund,
            refund: isExpense(form.category_id) && form.refund,
            // Noon UTC is that day in Switzerland all year (as a date-only import); today unchanged: now, with its time
            ...(form.date && form.date !== (editing ? originalDay : localDay()) ? { date: `${form.date}T12:00:00Z` } : {}),
        };
        try {
            if (editing) {
                await api.put(`/api/v1/transactions/${editing.id}`, fields);
            } else {
                await api.post('/api/v1/transactions', { ...fields, account_id: account.id });
            }
            onSaved();
        } catch (error) {
            console.error('Failed to save transaction', error);
            onError(errorMessage(error, t('transactions.saveFailed')));
        }
    };

    return (
        <form ref={formRef} onSubmit={handleSubmit} className="scroll-mt-4 mb-4 p-4 bg-slate-800/30 rounded-lg">
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
                type="date"
                aria-label={t('transactions.date')}
                value={form.date}
                max={localDay()}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
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
                    asset_id: isExpense(e.target.value) ? form.asset_id : '',
                    asset_purchase: isExpense(e.target.value) && form.asset_purchase
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
            {isExpense(form.category_id) && (
                <label className="flex items-center gap-2 mb-2 text-sm text-slate-300">
                    <input type="checkbox" checked={form.refund} onChange={e => setForm({ ...form, refund: e.target.checked })} />
                    {t('transactions.refund')}
                </label>
            )}
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
                <AssetLink assets={assets} assetId={form.asset_id} purchase={form.asset_purchase} className={field}
                    onChange={(asset_id, asset_purchase) => setForm({ ...form, asset_id, asset_purchase })} />
            )}
            <div className="flex gap-2">
                <button type="submit" className="btn-primary flex-1">
                    {editing ? t('transactions.saveChanges') : t('transactions.addTransaction')}
                </button>
                {editing && (
                    <button type="button" onClick={onCancel} className="px-4 text-slate-400 hover:text-white">
                        {t('common.cancel')}
                    </button>
                )}
            </div>
        </form>
    );
}
