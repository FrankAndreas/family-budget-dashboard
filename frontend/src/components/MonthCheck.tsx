import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { money } from '../finance';

interface Account { id: string; name: string }
interface Month { month: string; money_in: number; money_out: number; difference: number; booked: boolean }

const monthName = (month: string) =>
    new Date(`${month}-15T12:00:00`).toLocaleDateString('en', { month: 'long', year: 'numeric' });

// Clearing accounts (Migros, ...) should add up to 0 every month: money in by transfer, out by receipts.
// The gap is booked once per month: "Unknown expense", or "Other Income" when the receipts exceed the money.
export default function MonthCheck<A extends Account>({ accounts, canBook, version, onBooked }: {
    accounts: A[];
    canBook: (account: A) => boolean;
    version: number;
    onBooked: () => void;
}) {
    const [months, setMonths] = useState<Record<string, Month[]>>({});
    const [error, setError] = useState('');
    // The parent passes a freshly filtered list on every render; reload only when the accounts really change
    const ids = accounts.map(a => a.id).join(',');

    useEffect(() => {
        if (!ids) return;
        Promise.all(ids.split(',').map(id =>
            api.get(`/api/v1/accounts/${id}/month-check`).then(r => [id, r.data as Month[]] as const)))
            .then(entries => setMonths(Object.fromEntries(entries)))
            .catch(err => setError(errorMessage(err, 'Failed to load the month check')));
    }, [ids, version]);

    if (!accounts.length) return null;

    const book = async (account: A, month: Month) => {
        try {
            await api.post(`/api/v1/accounts/${account.id}/month-check/${month.month}`);
            setError('');
            onBooked();
        } catch (err) {
            setError(errorMessage(err, 'Failed to book the month check'));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-xl font-bold mb-1">Month check</h2>
            <p className="text-sm text-slate-400 mb-4">
                Clearing accounts should end every month at 0. What's left is booked once: money without receipts as
                "Unknown expense", receipts paid by gift card or vouchers as "Other Income".
            </p>
            {error && <p className="text-red-400 text-sm mb-2">{error}</p>}
            {accounts.map(account => {
                const open = months[account.id] ?? [];
                return (
                    <div key={account.id} className="mb-4">
                        <h3 className="font-semibold">{account.name}</h3>
                        {open.length === 0 ? (
                            <p className="text-sm text-emerald-400">All months add up.</p>
                        ) : (
                            <ul className="space-y-2 mt-2">
                                {open.map(m => (
                                    <li key={m.month} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm p-2 rounded bg-slate-800/30">
                                        <span className="font-medium w-36">{monthName(m.month)}</span>
                                        <span className="text-slate-400">in {money(m.money_in)}</span>
                                        <span className="text-slate-400">out {money(m.money_out)}</span>
                                        <span>{m.difference > 0
                                            ? `not tracked ${money(m.difference)}`
                                            : `receipts over ${money(-m.difference)}`}</span>
                                        {m.booked ? (
                                            <span className="text-amber-400">Already booked; delete the month-check booking to book the new difference</span>
                                        ) : canBook(account) && (
                                            <button onClick={() => book(account, m)} className="btn-primary text-xs">
                                                {m.difference > 0 ? 'Book as Unknown expense' : 'Book as Other Income'}
                                            </button>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
