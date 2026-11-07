import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money, type Asset, type Split } from '../finance';
import { formatDate, formatMonth } from '../format';
import type { Account, BankRow, Category, Transaction } from '../accounts';
import type { FamilyUser } from '../family';
import { openAttachment, useReceiptReading, useTags } from '../receipts';
import ReceiptForm from './ReceiptForm';
import AssetLink from './AssetLink';
import { useScrollIntoView } from '../useScrollIntoView';

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
    // Family members a receipt item can be for
    people: FamilyUser[];
    splits: Split[];
    assets: Asset[];
    // A transaction was added, changed or deleted
    onChanged: () => void;
    onError: (message: string) => void;
}

const emptyForm = { amount: '', description: '', category_id: '', member_id: '', split_id: '', asset_id: '', asset_purchase: false };
const field = 'w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// The selected account's transactions, with the form to add or edit one
export default function Transactions({
    account, transactions, categories, canEdit, ownerName, isParentAccount, isParent, children, people, splits, assets,
    onChanged, onError
}: Props) {
    const { t } = useTranslation();
    const aiEnabled = useReceiptReading();
    const { tags } = useTags();
    // The receipt form: a new receipt, or an existing booking's items
    const [receiptFor, setReceiptFor] = useState<'new' | Transaction | null>(null);
    // Bookings whose items are shown
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const toggleExpanded = (id: string) => setExpanded(current => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
    });
    const categoryName = (id: string) => categories.find(c => c.id === id)?.name ?? '';
    const personName = (id?: string | null) => people.find(p => p.id === id)?.username;
    const tagLabel = (id: string) => {
        const tag = tags.find(x => x.id === id);
        return tag ? `${tag.icon ? `${tag.icon} ` : ''}${tag.name}` : '';
    };
    // Open points (bank import, part 2): the bookings and bank lines still to sort out
    const [openOnly, setOpenOnly] = useState(false);
    const [openBookings, setOpenBookings] = useState<Transaction[]>([]);
    const [unlinked, setUnlinked] = useState<BankRow[]>([]);
    // Category chosen to book a bank line without booking, per line
    const [bookAs, setBookAs] = useState<Record<string, string>>({});
    useEffect(() => {
        // Reloaded whenever the list changes (after every action), so both views stay in step
        api.get(`/api/v1/accounts/${account.id}/bank-rows`, { params: { unlinked: 1 } })
            .then(res => setUnlinked(res.data)).catch(() => setUnlinked([]));
        if (openOnly) {
            api.get(`/api/v1/accounts/${account.id}/transactions`, { params: { open: 1 } })
                .then(res => setOpenBookings(res.data)).catch(() => setOpenBookings([]));
        }
    }, [account.id, transactions, openOnly]);
    const shown = openOnly ? openBookings : transactions;
    // Finding a booking: words in the text, category, items, child or item; and one category
    const [query, setQuery] = useState('');
    const [categoryFilter, setCategoryFilter] = useState('');
    const act = async (call: () => Promise<unknown>) => {
        try {
            await call();
            onChanged();
        } catch (error) {
            onError(errorMessage(error, t('transactions.saveFailed')));
        }
    };
    const linkRow = (transactionId: string, rowId: string) =>
        act(() => api.post(`/api/v1/transactions/${transactionId}/bank-rows/${rowId}`));
    const unlinkRow = (transactionId: string, rowId: string) =>
        act(() => api.delete(`/api/v1/transactions/${transactionId}/bank-rows/${rowId}`));
    const setFlag = (transaction: Transaction, flag: 'receipt_expected' | 'difference_accepted', value: boolean) =>
        act(() => api.put(`/api/v1/transactions/${transaction.id}`, { [flag]: value }));
    const bookRow = (row: BankRow) =>
        act(() => api.post(`/api/v1/bank-rows/${row.id}/book`, { category_id: bookAs[row.id] }));
    const badges = (transaction: Transaction) => {
        const state = transaction.state;
        if (!state) return [];
        const found: { text: string; warn: boolean }[] = [];
        if (state.confirmation === 'not_confirmed') found.push({ text: t('reconcile.notConfirmed'), warn: false });
        if (state.confirmation === 'no_payment') found.push({ text: t('reconcile.noPayment'), warn: true });
        if (state.confirmation === 'partly_paid') {
            const paid = (transaction.bank_rows ?? []).reduce((sum, r) => sum + r.amount, 0);
            found.push({ text: t('reconcile.partlyPaid', { paid: money(paid), total: money(transaction.amount) }), warn: true });
        }
        if (state.receipt_missing) found.push({ text: t('reconcile.receiptMissing'), warn: true });
        if (state.differs) found.push({ text: t('reconcile.differs', { amount: money(transaction.difference ?? 0) }), warn: true });
        return found;
    };
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState(emptyForm);
    // Set while the form is editing an existing transaction instead of adding one
    const [editingId, setEditingId] = useState<string | null>(null);
    const formRef = useScrollIntoView<HTMLFormElement>(editingId);

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

    const categoryLabel = (id: string) => {
        const category = categories.find(c => c.id === id);
        return category ? `${category.icon ? `${category.icon} ` : ''}${category.name}` : '';
    };
    // A receipt split into items of several categories shows that instead of the booking's one
    const rowCategory = (transaction: Transaction) => {
        const ids = new Set((transaction.items ?? []).map(item => item.category_id));
        return ids.size > 1 ? t('transactions.severalCategories') : categoryLabel(ids.size === 1 ? [...ids][0] : transaction.category_id);
    };
    const categoriesOf = (transaction: Transaction) =>
        [transaction.category_id, ...(transaction.items ?? []).map(item => item.category_id)];
    const matches = (transaction: Transaction) => {
        if (categoryFilter && !categoriesOf(transaction).includes(categoryFilter)) return false;
        const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
        if (words.length === 0) return true;
        const text = [
            transaction.description, money(transaction.amount), Math.abs(transaction.amount).toFixed(2),
            memberName(transaction.member_id), assetName(transaction.asset_id),
            ...categoriesOf(transaction).map(categoryName),
            ...(transaction.items ?? []).map(item => item.name),
        ].filter(Boolean).join(' ').toLowerCase();
        return words.every(word => text.includes(word));
    };
    const filtering = !!query.trim() || !!categoryFilter;
    const found = shown.filter(matches);
    // Newest first, one group per month (local time, as the dates are shown)
    const monthKey = (date: string) => {
        const d = new Date(date);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    };
    const months: { key: string; bookings: Transaction[]; income: number; expenses: number }[] = [];
    for (const transaction of found) {
        const key = monthKey(transaction.date);
        let month = months.find(m => m.key === key);
        if (!month) months.push(month = { key, bookings: [], income: 0, expenses: 0 });
        month.bookings.push(transaction);
        // Transfers move money between accounts: not income or expenses
        if (isTransfer(transaction)) continue;
        if (transaction.amount >= 0) month.income += transaction.amount;
        else month.expenses += transaction.amount;
    }
    months.sort((a, b) => b.key.localeCompare(a.key));
    // The categories of the bookings in the list, for the filter
    const usedCategories = categories
        .filter(c => shown.some(tr => categoriesOf(tr).includes(c.id)))
        .sort((a, b) => a.name.localeCompare(b.name));

    // A booking's actions: icons on a desktop, named buttons behind "⋯" on a phone
    const [menuFor, setMenuFor] = useState<string | null>(null);
    const rowActions = (transaction: Transaction) => {
        if (!canEdit) return [];
        const actions: { key: string; icon: string; name: string; label: string; danger?: boolean; run: () => void }[] = [];
        if (!transaction.items?.length && isExpense(transaction.category_id)) {
            actions.push({ key: 'split', icon: '🧾', name: t('transactions.splitShort'), label: t('receipt.split'),
                run: () => { closeForm(); setReceiptFor(transaction); } });
        }
        if (!isTransfer(transaction)) {
            actions.push({ key: 'edit', icon: '✎', name: t('transactions.editShort'), label: t('transactions.edit'),
                run: () => transaction.items?.length ? (closeForm(), setReceiptFor(transaction)) : handleEdit(transaction) });
        }
        // Settle up is undone in the Common tab; imported transfers can be deleted here
        if (!isSettleUp(transaction)) {
            actions.push({ key: 'delete', icon: '✕', name: t('transactions.deleteShort'), label: t('transactions.delete'),
                danger: true, run: () => void handleDelete(transaction) });
        }
        return actions;
    };

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
            asset_id: transaction.asset_id || '',
            asset_purchase: !!transaction.asset_purchase
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
            asset_id: form.asset_id || null,
            asset_purchase: !!form.asset_id && form.asset_purchase
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
        <div className="glass-card p-4 sm:p-6">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
                <h2 className="text-xl font-bold">
                    {t('transactions.title')}
                    {(account.open_points ?? 0) > 0 && (
                        <button onClick={() => setOpenOnly(!openOnly)}
                            className={`ml-3 text-sm font-normal px-2 py-0.5 rounded-full ${openOnly ? 'bg-amber-500/40 text-white' : 'bg-amber-500/20 text-amber-300'}`}>
                            {openOnly ? t('reconcile.showAll') : t('reconcile.openPoints', { count: account.open_points })}
                        </button>
                    )}
                </h2>
                {canEdit && (
                    <div className="flex flex-wrap justify-end gap-2">
                        <button onClick={() => { closeForm(); setReceiptFor(receiptFor ? null : 'new'); }} className="btn-secondary text-sm">
                            {aiEnabled ? t('receipt.open') : t('receipt.openWithoutAi')}
                        </button>
                        <button onClick={() => { setReceiptFor(null); if (showForm) closeForm(); else setShowForm(true); }}
                            className="btn-primary text-sm">
                            {t('transactions.add')}
                        </button>
                    </div>
                )}
            </div>

            {receiptFor && canEdit && (
                <ReceiptForm
                    key={receiptFor === 'new' ? 'new' : receiptFor.id}
                    account={account}
                    categories={expenseCategories}
                    people={people}
                    aiEnabled={aiEnabled}
                    assets={isParent ? assets : undefined}
                    transaction={receiptFor === 'new' ? undefined : receiptFor}
                    onSaved={() => { setReceiptFor(null); onChanged(); }}
                    onCancel={() => setReceiptFor(null)}
                />
            )}

            {!canEdit && (
                <p className="text-sm text-slate-400 mb-3">
                    {t('transactions.readOnly', { owner: ownerName ?? t('transactions.theOwner') })}
                </p>
            )}

            {showForm && canEdit && (
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

            {openOnly && unlinked.length > 0 && (
                <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-sm space-y-2">
                    <h3 className="font-semibold">{t('reconcile.rowsWithoutBooking')}</h3>
                    {unlinked.map(row => (
                        <div key={row.id} className="flex flex-wrap items-center gap-2">
                            <span className="flex-1 min-w-40">{formatDate(row.booked_on)} · {row.text}</span>
                            <span className="w-24 text-right">{money(row.amount)}</span>
                            {canEdit && (<>
                                <select value={bookAs[row.id] ?? ''} onChange={e => setBookAs({ ...bookAs, [row.id]: e.target.value })}
                                    aria-label={t('reconcile.bookAs', { text: row.text })}
                                    className="p-1 rounded bg-slate-800/50 border border-slate-600 text-white">
                                    <option value="">{t('reconcile.chooseCategory')}</option>
                                    {[...(row.amount < 0 ? expenseCategories : incomeCategories), ...categories.filter(c => c.system_key === 'TRANSFER')]
                                        // Not the ones the app books itself
                                        .filter(c => c.system_key !== 'UNKNOWN_EXPENSE')
                                        .map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                </select>
                                <button disabled={!bookAs[row.id]} onClick={() => bookRow(row)}
                                    className="text-sky-400 hover:underline disabled:opacity-40">{t('reconcile.book')}</button>
                            </>)}
                        </div>
                    ))}
                </div>
            )}

            {shown.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-4">
                    <input type="search" value={query} onChange={e => setQuery(e.target.value)}
                        aria-label={t('transactions.search')} placeholder={t('transactions.search')}
                        className="flex-1 min-w-48 p-2 rounded bg-slate-800/50 border border-slate-600 text-white" />
                    <select value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}
                        aria-label={t('transactions.filterCategory')}
                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white">
                        <option value="">{t('transactions.allCategories')}</option>
                        {usedCategories.map(c => <option key={c.id} value={c.id}>{categoryLabel(c.id)}</option>)}
                    </select>
                    {filtering && (
                        <button type="button" onClick={() => { setQuery(''); setCategoryFilter(''); }}
                            className="px-3 text-sm text-slate-400 hover:text-white">
                            {t('transactions.clearFilter')}
                        </button>
                    )}
                </div>
            )}

            <div className="space-y-6">
                {shown.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('transactions.none')}</p>
                ) : found.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('transactions.noneFound')}</p>
                ) : (
                    months.map(month => (
                        <section key={month.key} aria-label={formatMonth(month.key)}>
                            <div className="flex flex-wrap justify-between items-baseline gap-x-3 mb-2 px-1">
                                <h3 className="font-semibold text-slate-200">{formatMonth(month.key)}</h3>
                                <p className="text-sm text-slate-400" data-testid="month-totals">
                                    {month.income > 0 && <span className="text-emerald-400">+ {money(month.income)}</span>}
                                    {month.income > 0 && month.expenses < 0 && ' · '}
                                    {month.expenses < 0 && <span className="text-red-400">{money(month.expenses)}</span>}
                                    {filtering && ` · ${t('transactions.foundCount', { count: month.bookings.length })}`}
                                </p>
                            </div>
                            <div className="space-y-2">
                                {month.bookings.map(transaction => (
                                    <div key={transaction.id} className="px-3 py-2 sm:p-3 bg-slate-800/30 rounded-lg">
                                    <div className="flex justify-between items-center gap-2">
                                        <div className="min-w-0 flex-1">
                                            <p className="font-semibold break-words">
                                                {transaction.description || t('transactions.noDescription')}
                                                {memberName(transaction.member_id) && (
                                                    <span className="ml-2 inline-block whitespace-nowrap text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                                                        {t('transactions.forBadge', { name: memberName(transaction.member_id) })}
                                                    </span>
                                                )}
                                                {assetName(transaction.asset_id) && (
                                                    <span className="ml-2 inline-block whitespace-nowrap text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                                                        {assetName(transaction.asset_id)}
                                                    </span>
                                                )}
                                                {(transaction.split_id || transaction.split_shares) && (
                                                    <span className="ml-2 inline-block whitespace-nowrap text-xs font-normal px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300">
                                                        {t('transactions.sharedBadge')}
                                                    </span>
                                                )}
                                                {badges(transaction).map(badge => (
                                                    <span key={badge.text} className={`ml-2 inline-block whitespace-nowrap text-xs font-normal px-2 py-0.5 rounded-full ${badge.warn
                                                        ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-500/20 text-slate-300'}`}>
                                                        {badge.text}
                                                    </span>
                                                ))}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                                            <p className={`text-lg sm:text-xl font-bold whitespace-nowrap ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                {transaction.amount >= 0 ? '+ ' : ''}{money(transaction.amount)}
                                            </p>
                                            {/* Desktop: the actions as icons */}
                                            <div className="hidden sm:flex items-center gap-1">
                                                {rowActions(transaction).map(action => (
                                                    <button key={action.key} onClick={action.run} title={action.label} aria-label={action.label}
                                                        className={`w-10 h-10 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-700/40 transition-colors ${action.danger ? 'ml-2 hover:text-red-400' : 'hover:text-blue-400'}`}>
                                                        {action.icon}
                                                    </button>
                                                ))}
                                            </div>
                                            {/* Phone: one button keeps the row on one line; the actions open below it with their names */}
                                            {rowActions(transaction).length > 0 && (
                                                <button onClick={() => setMenuFor(menuFor === transaction.id ? null : transaction.id)}
                                                    aria-label={t('transactions.actions')} aria-expanded={menuFor === transaction.id}
                                                    className="sm:hidden w-10 h-10 flex items-center justify-center rounded-lg text-xl text-slate-400 hover:bg-slate-700/40">
                                                    ⋯
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                    {/* Under the description and amount, across the whole row: on a phone it has room there */}
                                    <p className="text-sm text-slate-400 -mt-1">
                                        {formatDate(transaction.date)}
                                        {rowCategory(transaction) && <span className="ml-2">· {rowCategory(transaction)}</span>}
                                        {(transaction.items?.length || transaction.attachments?.length || transaction.bank_rows?.length || transaction.state) ? (
                                            <button onClick={() => toggleExpanded(transaction.id)} className="ml-3 text-sky-400 hover:underline">
                                                {transaction.items?.length ? t('receipt.items', { count: transaction.items.length }) : ''}
                                                {transaction.attachments?.length ? ` ${t('receipt.attachmentsCount', { count: transaction.attachments.length })}` : ''}
                                                {transaction.bank_rows?.length ? ` ${t('reconcile.bankLines', { count: transaction.bank_rows.length })}` : ''}
                                                {!transaction.items?.length && !transaction.attachments?.length && !transaction.bank_rows?.length ? t('reconcile.more') : ''}
                                            </button>
                                        ) : null}
                                    </p>
                                    {menuFor === transaction.id && (
                                        <div className="sm:hidden mt-2 flex flex-wrap gap-2">
                                            {rowActions(transaction).map(action => (
                                                <button key={action.key} onClick={() => { setMenuFor(null); action.run(); }} aria-label={action.label}
                                                    className={`h-10 px-3 rounded-lg border text-sm ${action.danger ? 'border-red-500/40 text-red-300' : 'border-slate-600 text-slate-200'}`}>
                                                    {action.icon} {action.name}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    {expanded.has(transaction.id) && (
                                        <div className="mt-2 pt-2 border-t border-slate-700 text-sm space-y-1">
                                            {transaction.items?.map(item => (
                                                <div key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                                    <span className="flex-1 min-w-32">{item.name}</span>
                                                    <span className="text-slate-400">{categoryName(item.category_id)}</span>
                                                    {item.tag_ids.map(id => (
                                                        <span key={id} className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-200">{tagLabel(id)}</span>
                                                    ))}
                                                    {personName(item.person_id) && (
                                                        <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">{personName(item.person_id)}</span>
                                                    )}
                                                    <span className="w-24 text-right">{money(item.amount)}</span>
                                                </div>
                                            ))}
                                            {transaction.attachments?.map(a => (
                                                <button key={a.id} onClick={() => openAttachment(a)} className="block text-sky-400 hover:underline">
                                                    📎 {a.filename}
                                                </button>
                                            ))}
                                            {transaction.bank_rows?.map(row => (
                                                <div key={row.id} className="flex flex-wrap items-center gap-x-3 text-slate-300">
                                                    <span className="flex-1 min-w-32">🏦 {formatDate(row.booked_on)} · {row.text}</span>
                                                    <span className="w-24 text-right">{money(row.amount)}</span>
                                                    {canEdit && (
                                                        <button onClick={() => unlinkRow(transaction.id, row.id)} className="text-slate-500 hover:text-red-400">
                                                            {t('reconcile.unlink')}
                                                        </button>
                                                    )}
                                                </div>
                                            ))}
                                            {canEdit && transaction.state && (
                                                <div className="flex flex-wrap items-center gap-3 pt-1">
                                                    {unlinked.length > 0 && (
                                                        <select value="" onChange={e => e.target.value && linkRow(transaction.id, e.target.value)}
                                                            aria-label={t('reconcile.linkLine')}
                                                            className="p-1 rounded bg-slate-800/50 border border-slate-600 text-white">
                                                            <option value="">{t('reconcile.linkLine')}</option>
                                                            {unlinked.map(row => (
                                                                <option key={row.id} value={row.id}>{formatDate(row.booked_on)} · {row.text} · {money(row.amount)}</option>
                                                            ))}
                                                        </select>
                                                    )}
                                                    <label className="flex items-center gap-1">
                                                        <input type="checkbox" checked={!!transaction.receipt_expected}
                                                            onChange={e => setFlag(transaction, 'receipt_expected', e.target.checked)} />
                                                        {t('reconcile.receiptExpected')}
                                                    </label>
                                                    {transaction.state.differs && (
                                                        <button onClick={() => setFlag(transaction, 'difference_accepted', true)} className="text-sky-400 hover:underline">
                                                            {t('reconcile.acceptDifference')}
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    </div>
                                ))}
                            </div>
                        </section>
                    ))
                )}
            </div>
        </div>
    );
}
