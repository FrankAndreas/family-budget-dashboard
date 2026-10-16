import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { money, useSplits, type Overview } from '../finance';
import { formatDate } from '../format';
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
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits, reload: reloadSplits } = useSplits();
    const [balances, setBalances] = useState<Balance[]>([]);
    const [expenses, setExpenses] = useState<SharedExpense[]>([]);
    const [overview, setOverview] = useState<Overview>({ items: [], totals: {} });
    const [settlements, setSettlements] = useState<Settlement[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [settling, setSettling] = useState<
        { fromUser: string; toUser: string; amount: string; fromAccount: string; toAccount: string } | null
    >(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);
    const refresh = () => setVersion(v => v + 1);

    const parents = users.filter(u => u.role === 'PARENT' && u.is_active !== false);
    const isMe = (id: string) => id === user?.id;
    const nameOf = (id: string) => (isMe(id) ? t('common.you') : users.find(u => u.id === id)?.username ?? t('common.formerParent'));

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
            .catch(err => setError(errorMessage(err, t('commonBudget.loadFailed'))));
    }, [version, splits, t]);

    // Who owes most pays who is owed most (with two parents that's the whole balance)
    const byAmount = [...balances].sort((a, b) => a.amount - b.amount);
    const debtor = byAmount[0]?.amount < 0 ? byAmount[0] : undefined;
    const creditor = byAmount[byAmount.length - 1]?.amount > 0 ? byAmount[byAmount.length - 1] : undefined;
    const owed = debtor && creditor ? Math.min(-debtor.amount, creditor.amount) : 0;
    // Two parents: one sentence ("Dad owes you ..."); more: one line per parent
    const perParent = balances.length > 2;
    const lineFor = (b: Balance) => {
        const you = isMe(b.user_id);
        const name = nameOf(b.user_id);
        if (Math.abs(b.amount) < 0.005) return you ? t('commonBudget.youSettled') : t('commonBudget.nameSettled', { name });
        if (b.amount > 0) return t(you ? 'commonBudget.youOwed' : 'commonBudget.nameOwed', { name, amount: money(b.amount) });
        return t(you ? 'commonBudget.youOwe' : 'commonBudget.nameOwes', { name, amount: money(-b.amount) });
    };
    // "Dad owes you CHF 50.00" (two parents)
    const debtSentence = (from: string, to: string, amount: number) => {
        const values = { from: nameOf(from), to: nameOf(to), amount: money(amount) };
        if (isMe(from)) return t('commonBudget.youOweName', values);
        if (isMe(to)) return t('commonBudget.nameOwesYou', values);
        return t('commonBudget.nameOwesName', values);
    };
    // "16.10.2026: Dad paid you CHF 50.00"
    const paymentLine = (s: Settlement) => {
        const values = { date: formatDate(s.date), from: nameOf(s.from_user_id), to: nameOf(s.to_user_id), amount: money(s.amount) };
        if (isMe(s.from_user_id)) return t('commonBudget.youPaid', values);
        if (isMe(s.to_user_id)) return t('commonBudget.paidYou', values);
        return t('commonBudget.paid', values);
    };
    // Each parent pays from / receives into their own accounts; only accounts you can see are offered
    const accountsOf = (userId?: string) => accounts.filter(a => a.user_id === userId);
    const startSettling = () => {
        if (!debtor || !creditor) return;
        setSettling({
            fromUser: debtor.user_id,
            toUser: creditor.user_id,
            amount: owed.toFixed(2),
            fromAccount: accountsOf(debtor.user_id)[0]?.id ?? '',
            toAccount: accountsOf(creditor.user_id)[0]?.id ?? ''
        });
    };
    // Suggested amount for a chosen pair: what the payer owes, at most what the receiver is owed
    const suggested = (fromUser: string, toUser: string) => {
        const owes = -(balances.find(b => b.user_id === fromUser)?.amount ?? 0);
        const isOwed = balances.find(b => b.user_id === toUser)?.amount ?? 0;
        return Math.max(Math.min(owes, isOwed), 0).toFixed(2);
    };
    const choosePair = (fromUser: string, toUser: string) => settling && setSettling({
        ...settling,
        fromUser,
        toUser,
        amount: suggested(fromUser, toUser),
        fromAccount: fromUser === settling.fromUser ? settling.fromAccount : accountsOf(fromUser)[0]?.id ?? '',
        toAccount: toUser === settling.toUser ? settling.toAccount : accountsOf(toUser)[0]?.id ?? ''
    });

    const settle = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!settling) return;
        try {
            await api.post('/api/v1/settlements', {
                from_user_id: settling.fromUser,
                to_user_id: settling.toUser,
                amount: parseFloat(settling.amount),
                from_account_id: settling.fromAccount,
                to_account_id: settling.toAccount
            });
            setSettling(null);
            refresh();
        } catch (err) {
            setError(errorMessage(err, t('commonBudget.settleFailed')));
        }
    };

    const undoSettlement = async (settlement: Settlement) => {
        if (!confirm(t('commonBudget.confirmUndo', { amount: money(settlement.amount) }))) return;
        try {
            await api.delete(`/api/v1/settlements/${settlement.id}`);
            refresh();
        } catch (err) {
            setError(errorMessage(err, t('commonBudget.undoFailed')));
        }
    };

    if (parents.length < 2) {
        return (
            <div className="glass-card p-6">
                <h2 className="text-2xl font-bold mb-2">{t('commonBudget.title')}</h2>
                <p className="text-slate-400">{t('commonBudget.needsSecondParent')}</p>
            </div>
        );
    }

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="space-y-6">
            {error && (
                <div className="p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between">
                    <span>{error}</span>
                    <button onClick={() => setError('')} aria-label={t('common.dismissError')}>✕</button>
                </div>
            )}

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-2">{t('commonBudget.balance')}</h2>
                {perParent ? (
                    owed > 0 ? (
                        <ul className="space-y-1">
                            {[...byAmount].reverse().map(b => (
                                <li key={b.user_id} className={`text-lg font-semibold ${b.amount > 0.005 ? 'text-emerald-400' : b.amount < -0.005 ? 'text-red-300' : 'text-slate-400'}`}>
                                    {lineFor(b)}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="text-2xl font-bold text-emerald-400">{t('commonBudget.allSettled')}</p>
                    )
                ) : owed > 0 && debtor && creditor ? (
                    <p className="text-2xl font-bold">{debtSentence(debtor.user_id, creditor.user_id, owed)}</p>
                ) : (
                    <p className="text-2xl font-bold text-emerald-400">{t('commonBudget.allSettled')}</p>
                )}
                {owed > 0 && !settling && (
                    <button
                        onClick={startSettling}
                        className="btn-primary text-sm mt-3"
                    >
                        {t('commonBudget.settleUp')}
                    </button>
                )}
                {settling && (
                    <form onSubmit={settle} className="mt-4 p-4 bg-slate-800/30 rounded-lg space-y-2">
                        {perParent && (['fromUser', 'toUser'] as const).map(key => (
                            <select
                                key={key}
                                value={settling[key]}
                                onChange={(e) => key === 'fromUser'
                                    ? choosePair(e.target.value, settling.toUser)
                                    : choosePair(settling.fromUser, e.target.value)}
                                className={input}
                                aria-label={key === 'fromUser' ? t('commonBudget.whoPays') : t('commonBudget.whoReceives')}
                                required
                            >
                                {balances.map(b => (
                                    <option key={b.user_id} value={b.user_id}>
                                        {t(key === 'fromUser' ? 'commonBudget.pays' : 'commonBudget.receives', { name: nameOf(b.user_id) })}
                                    </option>
                                ))}
                            </select>
                        ))}
                        <input
                            type="number" step="0.01" min="0.01"
                            value={settling.amount}
                            onChange={(e) => setSettling({ ...settling, amount: e.target.value })}
                            className={input}
                            aria-label={t('commonBudget.amount')}
                            required
                        />
                        {[
                            {
                                key: 'fromAccount' as const, owner: settling.fromUser, label: isMe(settling.fromUser)
                                    ? t('commonBudget.fromYourAccount') : t('commonBudget.fromNamesAccount', { name: nameOf(settling.fromUser) }),
                            },
                            {
                                key: 'toAccount' as const, owner: settling.toUser, label: isMe(settling.toUser)
                                    ? t('commonBudget.toYourAccount') : t('commonBudget.toNamesAccount', { name: nameOf(settling.toUser) }),
                            },
                        ].map(field => (
                            <select
                                key={field.key}
                                value={settling[field.key]}
                                onChange={(e) => setSettling({ ...settling, [field.key]: e.target.value })}
                                className={input}
                                aria-label={field.label}
                                required
                            >
                                <option value="">{field.label}</option>
                                {accountsOf(field.owner).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                            </select>
                        ))}
                        <p className="text-xs text-slate-500">{t('commonBudget.accountsHint')}</p>
                        <div className="flex gap-2">
                            <button type="submit" className="btn-primary flex-1">{t('commonBudget.recordPayment')}</button>
                            <button type="button" onClick={() => setSettling(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                        </div>
                    </form>
                )}
                {settlements.length > 0 && (
                    <div className="mt-4 space-y-1 text-sm text-slate-400">
                        {settlements.slice(0, 5).map(s => (
                            <div key={s.id} className="flex justify-between gap-2">
                                <span>{paymentLine(s)}</span>
                                <button onClick={() => undoSettlement(s)} className="hover:text-red-400">{t('commonBudget.undo')}</button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-1">{t('commonBudget.monthlyShares')}</h2>
                <p className="text-sm text-slate-400 mb-4">{t('commonBudget.monthlySharesIntro')}</p>
                {overview.items.length === 0 ? (
                    <p className="text-slate-400 text-sm">{t('commonBudget.nothingPlanned')}</p>
                ) : (
                    <div className="space-y-1">
                        {overview.items.map(item => (
                            <div key={item.id} className="flex justify-between p-2 bg-slate-800/30 rounded">
                                <span>{item.kind === 'asset' ? '📦 ' : ''}{item.name}</span>
                                <span>{t('common.perMonth', { amount: money(item.monthly) })}</span>
                            </div>
                        ))}
                        <div className="flex flex-wrap gap-4 pt-3 font-bold">
                            {parents.map(p => (
                                <span key={p.id}>{nameOf(p.id)}: {t('common.perMonth', { amount: money(overview.totals[p.id] ?? 0) })}</span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <MonthlyCosts splits={splits} onChange={refresh} />

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">{t('commonBudget.sharedExpenses')}</h2>
                {expenses.length === 0 ? (
                    <p className="text-slate-400 text-sm">{t('commonBudget.noSharedExpenses')}</p>
                ) : (
                    <div className="space-y-2">
                        {expenses.slice(0, 30).map(e => (
                            <div key={e.transaction_id} className="p-3 bg-slate-800/30 rounded-lg flex flex-wrap justify-between gap-2">
                                <div>
                                    <p className="font-semibold">{e.description || t('common.noDescription')}</p>
                                    <p className="text-sm text-slate-400">
                                        {t(isMe(e.payer_id) ? 'commonBudget.paidByYou' : 'commonBudget.paidBy', {
                                            date: formatDate(e.date), name: nameOf(e.payer_id), split: e.split_name ?? t('commonBudget.deletedSplit'),
                                        })}
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
