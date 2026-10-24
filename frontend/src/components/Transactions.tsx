import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money, type Asset, type Split } from '../finance';
import { formatDate } from '../format';
import type { Account, BankRow, Category, Transaction } from '../accounts';
import type { FamilyUser } from '../family';
import { openAttachment, useReceiptReading, useTags } from '../receipts';
import ReceiptForm from './ReceiptForm';
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

const emptyForm = { amount: '', description: '', category_id: '', member_id: '', split_id: '', asset_id: '' };
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
                        <button onClick={() => { closeForm(); setReceiptFor(receiptFor ? null : 'new'); }} className="btn-primary text-sm">
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

            <div className="space-y-2">
                {shown.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('transactions.none')}</p>
                ) : (
                    shown.map(transaction => (
                        <div key={transaction.id} className="p-3 bg-slate-800/30 rounded-lg">
                        <div className="flex justify-between items-start sm:items-center gap-2">
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
                                <p className="text-sm text-slate-400">
                                    {formatDate(transaction.date)}
                                    {(transaction.items?.length || transaction.attachments?.length || transaction.bank_rows?.length || transaction.state) ? (
                                        <button onClick={() => toggleExpanded(transaction.id)} className="ml-3 text-sky-400 hover:underline">
                                            {transaction.items?.length ? t('receipt.items', { count: transaction.items.length }) : ''}
                                            {transaction.attachments?.length ? ` ${t('receipt.attachmentsCount', { count: transaction.attachments.length })}` : ''}
                                            {transaction.bank_rows?.length ? ` ${t('reconcile.bankLines', { count: transaction.bank_rows.length })}` : ''}
                                            {!transaction.items?.length && !transaction.attachments?.length && !transaction.bank_rows?.length ? t('reconcile.more') : ''}
                                        </button>
                                    ) : null}
                                </p>
                            </div>
                            <div className="flex flex-col sm:flex-row items-end sm:items-center gap-1 sm:gap-2 shrink-0">
                                <p className={`text-lg sm:text-xl font-bold whitespace-nowrap ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {transaction.amount >= 0 ? '+ ' : ''}{money(transaction.amount)}
                                </p>
                                <div className="flex items-center gap-1">
                                {canEdit && !transaction.items?.length && isExpense(transaction.category_id) && (
                                    <button
                                        onClick={() => { closeForm(); setReceiptFor(transaction); }}
                                        className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-700/40 hover:text-blue-400 transition-colors"
                                        title={t('receipt.split')}
                                        aria-label={t('receipt.split')}
                                    >
                                        🧾
                                    </button>
                                )}
                                {canEdit && !isTransfer(transaction) && (
                                    <button
                                        onClick={() => transaction.items?.length
                                            ? (closeForm(), setReceiptFor(transaction))
                                            : handleEdit(transaction)}
                                        className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-700/40 hover:text-blue-400 transition-colors"
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
                                        className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-700/40 ml-2 hover:text-red-400 transition-colors"
                                        title={t('transactions.delete')}
                                        aria-label={t('transactions.delete')}
                                    >
                                        ✕
                                    </button>
                                )}
                                </div>
                            </div>
                        </div>
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
                    ))
                )}
            </div>
        </div>
    );
}
