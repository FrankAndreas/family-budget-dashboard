import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { money, useSplits, type Overview } from '../finance';
import SplitManager from './SplitManager';
import MonthlyCosts from './MonthlyCosts';

interface Balance { user_id: string; amount: number }
interface SharedExpense {
    transaction_id: string;
    date: string;
    description: string | null;
    amount: number;
    payer_id: string;
    split_name: string | null;
    shares: Record<string, number>;
}
interface Account { id: string; user_id: string; name: string }
interface Settlement { id: string; from_user_id: string; to_user_id: string; amount: number; date: string }

// Costs the parents share: who owes whom, each parent's monthly share, and the splits
export default function CommonBudget() {
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits, reload: reloadSplits } = useSplits();
    const [balances, setBalances] = useState<Balance[]>([]);
    const [expenses, setExpenses] = useState<SharedExpense[]>([]);
    const [overview, setOverview] = useState<Overview>({ items: [], totals: {} });
    const [settlements, setSettlements] = useState<Settlement[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [settling, setSettling] = useState<{ amount: string; fromAccount: string; toAccount: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);
    const refresh = () => setVersion(v => v + 1);

    const parents = users.filter(u => u.role === 'PARENT' && u.is_active !== false);
    const nameOf = (id: string) => (id === user?.id ? 'You' : users.find(u => u.id === id)?.username ?? 'former parent');

    useEffect(() => {
        Promise.all([
            api.get('/api/v1/common/balance'),
            api.get('/api/v1/common/expenses'),
            api.get('/api/v1/common/overview'),
            api.get('/api/v1/settlements'),
            api.get('/api/v1/accounts')
        ])
            .then(([b, e, o, s, a]) => {
                setBalances(b.data);
                setExpenses(e.data);
                setOverview(o.data);
                setSettlements(s.data);
                setAccounts(a.data);
            })
            .catch(err => setError(errorMessage(err, 'Failed to load the common budget')));
    }, [version, splits]);

    // With two parents the balance is one number: who owes whom
    const debtor = balances.find(b => b.amount < 0);
    const creditor = balances.find(b => b.amount > 0);
    const owed = creditor ? creditor.amount : 0;
    // Each parent pays from / receives into their own accounts; only accounts you can see are offered
    const accountsOf = (userId?: string) => accounts.filter(a => a.user_id === userId);

    const settle = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!settling || !debtor || !creditor) return;
        try {
            await api.post('/api/v1/settlements', {
                from_user_id: debtor.user_id,
                to_user_id: creditor.user_id,
                amount: parseFloat(settling.amount),
                from_account_id: settling.fromAccount,
                to_account_id: settling.toAccount
            });
            setSettling(null);
            refresh();
        } catch (err) {
            setError(errorMessage(err, 'Failed to settle up'));
        }
    };

    const undoSettlement = async (settlement: Settlement) => {
        if (!confirm(`Undo the payment of ${money(settlement.amount)}? Both transfer transactions are removed.`)) return;
        try {
            await api.delete(`/api/v1/settlements/${settlement.id}`);
            refresh();
        } catch (err) {
            setError(errorMessage(err, 'Failed to undo'));
        }
    };

    if (parents.length < 2) {
        return (
            <div className="glass-card p-6">
                <h2 className="text-2xl font-bold mb-2">Common budget</h2>
                <p className="text-slate-400">Sharing costs needs a second parent. Add one in Settings → Family.</p>
            </div>
        );
    }

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="space-y-6">
            {error && (
                <div className="p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between">
                    <span>{error}</span>
                    <button onClick={() => setError('')} aria-label="Dismiss error">✕</button>
                </div>
            )}

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-2">Balance</h2>
                {owed > 0 && debtor && creditor ? (
                    <p className="text-2xl font-bold">
                        {nameOf(debtor.user_id)} {debtor.user_id === user?.id ? 'owe' : 'owes'}{' '}
                        {creditor.user_id === user?.id ? 'you' : nameOf(creditor.user_id)} {money(owed)}
                    </p>
                ) : (
                    <p className="text-2xl font-bold text-emerald-400">All settled</p>
                )}
                {owed > 0 && !settling && (
                    <button
                        onClick={() => setSettling({
                            amount: owed.toFixed(2),
                            fromAccount: accountsOf(debtor?.user_id)[0]?.id ?? '',
                            toAccount: accountsOf(creditor?.user_id)[0]?.id ?? ''
                        })}
                        className="btn-primary text-sm mt-3"
                    >
                        Settle up
                    </button>
                )}
                {settling && debtor && creditor && (
                    <form onSubmit={settle} className="mt-4 p-4 bg-slate-800/30 rounded-lg space-y-2">
                        <input
                            type="number" step="0.01" min="0.01"
                            value={settling.amount}
                            onChange={(e) => setSettling({ ...settling, amount: e.target.value })}
                            className={input}
                            aria-label="Amount"
                            required
                        />
                        {[
                            { key: 'fromAccount' as const, owner: debtor.user_id, label: `From ${nameOf(debtor.user_id)}'s account` },
                            { key: 'toAccount' as const, owner: creditor.user_id, label: `To ${nameOf(creditor.user_id)}'s account` }
                        ].map(field => (
                            <select
                                key={field.key}
                                value={settling[field.key]}
                                onChange={(e) => setSettling({ ...settling, [field.key]: e.target.value })}
                                className={input}
                                aria-label={field.label}
                                required
                            >
                                <option value="">{field.label.replace("You's", 'your')}</option>
                                {accountsOf(field.owner).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                            </select>
                        ))}
                        <p className="text-xs text-slate-500">
                            Only accounts you can see are listed. If the other parent's accounts are missing, they can
                            record the payment themselves, or share their finances with you.
                        </p>
                        <div className="flex gap-2">
                            <button type="submit" className="btn-primary flex-1">Record payment</button>
                            <button type="button" onClick={() => setSettling(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                        </div>
                    </form>
                )}
                {settlements.length > 0 && (
                    <div className="mt-4 space-y-1 text-sm text-slate-400">
                        {settlements.slice(0, 5).map(s => (
                            <div key={s.id} className="flex justify-between gap-2">
                                <span>{new Date(s.date).toLocaleDateString()}: {nameOf(s.from_user_id)} paid {nameOf(s.to_user_id).replace('You', 'you')} {money(s.amount)}</span>
                                <button onClick={() => undoSettlement(s)} className="hover:text-red-400">Undo</button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-1">Monthly shares</h2>
                <p className="text-sm text-slate-400 mb-4">
                    Common monthly costs, yearly bills (÷ 12) and investments (set-aside), divided by their split.
                </p>
                {overview.items.length === 0 ? (
                    <p className="text-slate-400 text-sm">Nothing planned yet. Add common costs below, or common yearly bills and investments in their tabs.</p>
                ) : (
                    <div className="space-y-1">
                        {overview.items.map(item => (
                            <div key={item.id} className="flex justify-between p-2 bg-slate-800/30 rounded">
                                <span>{item.kind === 'asset' ? '📦 ' : ''}{item.name}</span>
                                <span>{money(item.monthly)}/month</span>
                            </div>
                        ))}
                        <div className="flex flex-wrap gap-4 pt-3 font-bold">
                            {parents.map(p => (
                                <span key={p.id}>{nameOf(p.id)}: {money(overview.totals[p.id] ?? 0)}/month</span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <MonthlyCosts splits={splits} onChange={refresh} />

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">Shared expenses</h2>
                {expenses.length === 0 ? (
                    <p className="text-slate-400 text-sm">No shared expenses yet. When you add an expense, choose a split under "Shared".</p>
                ) : (
                    <div className="space-y-2">
                        {expenses.slice(0, 30).map(e => (
                            <div key={e.transaction_id} className="p-3 bg-slate-800/30 rounded-lg flex flex-wrap justify-between gap-2">
                                <div>
                                    <p className="font-semibold">{e.description || 'No description'}</p>
                                    <p className="text-sm text-slate-400">
                                        {new Date(e.date).toLocaleDateString()} · paid by {nameOf(e.payer_id).replace('You', 'you')} · {e.split_name ?? 'deleted split'}
                                    </p>
                                </div>
                                <div className="text-right">
                                    <p className="font-bold">{money(e.amount)}</p>
                                    <p className="text-xs text-slate-400">
                                        {Object.entries(e.shares).map(([id, amount]) => `${nameOf(id)} ${money(amount)}`).join(' · ')}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <SplitManager splits={splits} parents={parents} onChange={() => { reloadSplits(); refresh(); }} />
        </div>
    );
}
