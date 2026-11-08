// What the booking list shows about a booking, and how it finds and groups them; no React here
import type { TFunction } from 'i18next';
import type { Category, Transaction } from '../../accounts';
import type { FamilyUser } from '../../family';
import { money, type Asset } from '../../finance';
import type { Tag } from '../../receipts';

export interface Lookups {
    categoryName: (id: string) => string;
    // With its icon
    categoryLabel: (id: string) => string;
    isExpense: (categoryId: string) => boolean;
    isTransfer: (transaction: Transaction) => boolean;
    isSettleUp: (transaction: Transaction) => boolean;
    // A dependent child the booking is for
    memberName: (id?: string | null) => string | undefined;
    // The person a receipt item is for
    personName: (id?: string | null) => string | undefined;
    assetName: (id?: string | null) => string | undefined;
    tagLabel: (id: string) => string;
}

export function lookups(categories: Category[], children: FamilyUser[], people: FamilyUser[], assets: Asset[], tags: Tag[]): Lookups {
    const byId = <T extends { id: string }>(list: T[]) => new Map(list.map(x => [x.id, x]));
    const categoryMap = byId(categories);
    const category = (id: string) => categoryMap.get(id);
    const childMap = byId(children);
    const personMap = byId(people);
    const assetMap = byId(assets);
    const tagMap = byId(tags);
    return {
        categoryName: id => category(id)?.name ?? '',
        categoryLabel: id => {
            const found = category(id);
            return found ? `${found.icon ? `${found.icon} ` : ''}${found.name}` : '';
        },
        isExpense: id => category(id)?.type === 'EXPENSE',
        isTransfer: transaction => category(transaction.category_id)?.type === 'TRANSFER',
        isSettleUp: transaction => category(transaction.category_id)?.system_key === 'SETTLE_UP',
        memberName: id => (id ? childMap.get(id)?.username : undefined),
        personName: id => (id ? personMap.get(id)?.username : undefined),
        assetName: id => (id ? assetMap.get(id)?.name : undefined),
        tagLabel: id => {
            const tag = tagMap.get(id);
            return tag ? `${tag.icon ? `${tag.icon} ` : ''}${tag.name}` : '';
        },
    };
}

// The booking's category and those of its items
export const categoriesOf = (transaction: Transaction) =>
    [transaction.category_id, ...(transaction.items ?? []).map(item => item.category_id)];

// A receipt split into items of several categories shows that instead of the booking's one
export function rowCategory(transaction: Transaction, look: Lookups, t: TFunction): string {
    const ids = new Set((transaction.items ?? []).map(item => item.category_id));
    return ids.size > 1 ? t('transactions.severalCategories') : look.categoryLabel(ids.size === 1 ? [...ids][0] : transaction.category_id);
}

// Finding a booking: words in the text, category, items, child or investment; and one category
export function matches(transaction: Transaction, query: string, categoryFilter: string, look: Lookups): boolean {
    if (categoryFilter && !categoriesOf(transaction).includes(categoryFilter)) return false;
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) return true;
    const text = [
        transaction.description, money(transaction.amount), Math.abs(transaction.amount).toFixed(2),
        look.memberName(transaction.member_id), look.assetName(transaction.asset_id),
        ...categoriesOf(transaction).map(look.categoryName),
        ...(transaction.items ?? []).map(item => item.name),
    ].filter(Boolean).join(' ').toLowerCase();
    return words.every(word => text.includes(word));
}

export interface Month { key: string; bookings: Transaction[]; income: number; expenses: number }

// Newest first, one group per month (local time, as the dates are shown)
export function byMonth(bookings: Transaction[], isTransfer: (transaction: Transaction) => boolean): Month[] {
    const monthKey = (date: string) => {
        const d = new Date(date);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    };
    const months: Month[] = [];
    for (const transaction of bookings) {
        const key = monthKey(transaction.date);
        let month = months.find(m => m.key === key);
        if (!month) months.push(month = { key, bookings: [], income: 0, expenses: 0 });
        month.bookings.push(transaction);
        // Transfers move money between accounts: not income or expenses
        if (isTransfer(transaction)) continue;
        if (transaction.amount >= 0) month.income += transaction.amount;
        else month.expenses += transaction.amount;
    }
    return months.sort((a, b) => b.key.localeCompare(a.key));
}

// What the bank import says about a booking (bank import, part 2)
export function badges(transaction: Transaction, t: TFunction): { text: string; warn: boolean }[] {
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
}
