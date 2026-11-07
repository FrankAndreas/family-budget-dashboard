import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money, type Asset, type Split } from '../finance';
import { formatMonth } from '../format';
import type { Account, BankRow, Category, Transaction } from '../accounts';
import type { FamilyUser } from '../family';
import { useReceiptReading, useTags } from '../receipts';
import ReceiptForm from './ReceiptForm';
import { ask } from '../confirm';
import BookingForm from './transactions/BookingForm';
import BookingFilters from './transactions/BookingFilters';
import BookingRow, { type RowAction } from './transactions/BookingRow';
import UnlinkedBankRows from './transactions/UnlinkedBankRows';
import { byMonth, categoriesOf, lookups, matches } from './transactions/bookingList';

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

// The selected account's bookings: the forms to add or change one, open points, finding, and the list by month
export default function Transactions({
    account, transactions, categories, canEdit, ownerName, isParentAccount, isParent, children, people, splits, assets,
    onChanged, onError
}: Props) {
    const { t } = useTranslation();
    const aiEnabled = useReceiptReading();
    const { tags } = useTags();
    const look = lookups(categories, children, people, assets, tags);
    // The receipt form: a new receipt, or an existing booking's items
    const [receiptFor, setReceiptFor] = useState<'new' | Transaction | null>(null);
    // The plain booking form, and the booking it changes (none: a new one)
    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState<Transaction | null>(null);
    const closeForm = () => {
        setEditing(null);
        setShowForm(false);
    };
    // Bookings whose details are shown, and the one whose phone menu is open
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const toggleExpanded = (id: string) => setExpanded(current => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
    });
    const [menuFor, setMenuFor] = useState<string | null>(null);

    // Open points (bank import, part 2): the bookings and bank lines still to sort out
    const [openOnly, setOpenOnly] = useState(false);
    const [openBookings, setOpenBookings] = useState<Transaction[]>([]);
    const [unlinked, setUnlinked] = useState<BankRow[]>([]);
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

    const [query, setQuery] = useState('');
    const [categoryFilter, setCategoryFilter] = useState('');
    const filtering = !!query.trim() || !!categoryFilter;
    const found = shown.filter(transaction => matches(transaction, query, categoryFilter, look));
    const months = byMonth(found, look.isTransfer);
    // The categories of the bookings in the list, for the filter
    const usedCategories = categories
        .filter(c => shown.some(tr => categoriesOf(tr).includes(c.id)))
        .sort((a, b) => a.name.localeCompare(b.name));

    const act = async (call: () => Promise<unknown>) => {
        try {
            await call();
            onChanged();
        } catch (error) {
            onError(errorMessage(error, t('transactions.saveFailed')));
        }
    };

    const handleDelete = async (transaction: Transaction) => {
        if (!await ask(t('transactions.confirmDelete', {
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

    const rowActions = (transaction: Transaction): RowAction[] => {
        if (!canEdit) return [];
        const actions: RowAction[] = [];
        if (!transaction.items?.length && look.isExpense(transaction.category_id)) {
            actions.push({ key: 'split', icon: '🧾', name: t('transactions.splitShort'), label: t('receipt.split'),
                run: () => { closeForm(); setReceiptFor(transaction); } });
        }
        if (!look.isTransfer(transaction)) {
            actions.push({ key: 'edit', icon: '✎', name: t('transactions.editShort'), label: t('transactions.edit'),
                run: () => {
                    if (transaction.items?.length) {
                        closeForm();
                        setReceiptFor(transaction);
                    } else {
                        setEditing(transaction);
                        setShowForm(true);
                    }
                } });
        }
        // Settle up is undone in the Common tab; imported transfers can be deleted here
        if (!look.isSettleUp(transaction)) {
            actions.push({ key: 'delete', icon: '✕', name: t('transactions.deleteShort'), label: t('transactions.delete'),
                danger: true, run: () => void handleDelete(transaction) });
        }
        return actions;
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
                    categories={categories.filter(c => c.type === 'EXPENSE')}
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
                <BookingForm
                    key={editing?.id ?? 'new'}
                    account={account}
                    categories={categories}
                    editing={editing}
                    isParent={isParent}
                    isParentAccount={isParentAccount}
                    children={children}
                    splits={splits}
                    assets={assets}
                    onSaved={() => { closeForm(); onChanged(); }}
                    onCancel={closeForm}
                    onError={onError}
                />
            )}

            {openOnly && unlinked.length > 0 && (
                <UnlinkedBankRows rows={unlinked} categories={categories} canEdit={canEdit}
                    onBook={(row, categoryId) => act(() => api.post(`/api/v1/bank-rows/${row.id}/book`, { category_id: categoryId }))} />
            )}

            {shown.length > 0 && (
                <BookingFilters query={query} categoryFilter={categoryFilter} categories={usedCategories}
                    categoryLabel={look.categoryLabel} onQuery={setQuery} onCategory={setCategoryFilter} />
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
                                    <BookingRow
                                        key={transaction.id}
                                        transaction={transaction}
                                        look={look}
                                        canEdit={canEdit}
                                        actions={rowActions(transaction)}
                                        menuOpen={menuFor === transaction.id}
                                        onMenu={open => setMenuFor(open ? transaction.id : null)}
                                        expanded={expanded.has(transaction.id)}
                                        onToggleExpanded={() => toggleExpanded(transaction.id)}
                                        unlinked={unlinked}
                                        onLinkRow={rowId => act(() => api.post(`/api/v1/transactions/${transaction.id}/bank-rows/${rowId}`))}
                                        onUnlinkRow={rowId => act(() => api.delete(`/api/v1/transactions/${transaction.id}/bank-rows/${rowId}`))}
                                        onFlag={(flag, value) => act(() => api.put(`/api/v1/transactions/${transaction.id}`, { [flag]: value }))}
                                    />
                                ))}
                            </div>
                        </section>
                    ))
                )}
            </div>
        </div>
    );
}
