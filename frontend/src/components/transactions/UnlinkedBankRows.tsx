import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { BankRow, Category } from '../../accounts';
import { money } from '../../finance';
import { formatDate } from '../../format';

interface Props {
    rows: BankRow[];
    categories: Category[];
    canEdit: boolean;
    // Book the line as a new booking in that category
    onBook: (row: BankRow, categoryId: string) => void;
}

// Bank statement lines no booking is linked to (open points): each can be booked in a category here
export default function UnlinkedBankRows({ rows, categories, canEdit, onBook }: Props) {
    const { t } = useTranslation();
    // Category chosen per line
    const [bookAs, setBookAs] = useState<Record<string, string>>({});
    const income = categories.filter(c => c.type === 'INCOME');
    const expenses = categories.filter(c => c.type === 'EXPENSE');
    const transfers = categories.filter(c => c.system_key === 'TRANSFER');
    return (
        <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-sm space-y-2">
            <h3 className="font-semibold">{t('reconcile.rowsWithoutBooking')}</h3>
            {rows.map(row => (
                <div key={row.id} className="flex flex-wrap items-center gap-2">
                    <span className="flex-1 min-w-40">{formatDate(row.booked_on)} · {row.text}</span>
                    <span className="w-24 text-right">{money(row.amount)}</span>
                    {canEdit && (<>
                        <select value={bookAs[row.id] ?? ''} onChange={e => setBookAs({ ...bookAs, [row.id]: e.target.value })}
                            aria-label={t('reconcile.bookAs', { text: row.text })}
                            className="p-1 rounded bg-slate-800/50 border border-slate-500 text-white">
                            <option value="">{t('reconcile.chooseCategory')}</option>
                            {[...(row.amount < 0 ? expenses : income), ...transfers]
                                // Not the ones the app books itself
                                .filter(c => c.system_key !== 'UNKNOWN_EXPENSE')
                                .map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                        <button disabled={!bookAs[row.id]} onClick={() => onBook(row, bookAs[row.id])}
                            className="text-sky-400 hover:underline disabled:opacity-40">{t('reconcile.book')}</button>
                    </>)}
                </div>
            ))}
        </div>
    );
}
