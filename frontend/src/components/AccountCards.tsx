import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { money } from '../finance';
import { ACCOUNT_TYPES, type Account } from '../accounts';
import type { FamilyUser } from '../family';

interface Props {
    accounts: Account[];
    // Shown in the summary; the transactions themselves are listed by Transactions
    transactionCount: number;
    selectedAccount: string | null;
    onSelect: (accountId: string) => void;
    ownerOf: (account: Account) => FamilyUser | undefined;
    canEdit: (account: Account) => boolean;
    // An account was added or changed
    onChanged: () => void;
    onDeleted: (accountId: string) => void;
    onError: (message: string) => void;
}

const field = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// Summary cards and the account cards, with adding, renaming and deleting accounts
export default function AccountCards({
    accounts, transactionCount, selectedAccount, onSelect, ownerOf, canEdit, onChanged, onDeleted, onError
}: Props) {
    const { t } = useTranslation();
    const { user } = useAuth();
    const [showAddAccount, setShowAddAccount] = useState(false);
    const [newAccountName, setNewAccountName] = useState('');
    const [newAccountType, setNewAccountType] = useState('BANK');
    // Account being renamed (inline form on its card)
    const [editingAccount, setEditingAccount] = useState<{ id: string; name: string; type: string } | null>(null);

    // Your own money; accounts others shared with you are listed but not added up
    const totalBalance = accounts.filter(a => a.user_id === user?.id).reduce((sum, acc) => sum + acc.balance, 0);

    const handleAddAccount = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/accounts', { name: newAccountName, type: newAccountType });
            setNewAccountName('');
            setShowAddAccount(false);
            onChanged();
        } catch (error) {
            console.error('Failed to create account', error);
            onError(errorMessage(error, t('accounts.createFailed')));
        }
    };

    const handleSaveAccount = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingAccount) return;
        try {
            await api.put(`/api/v1/accounts/${editingAccount.id}`, { name: editingAccount.name, type: editingAccount.type });
            setEditingAccount(null);
            onChanged();
        } catch (error) {
            console.error('Failed to update account', error);
            onError(errorMessage(error, t('accounts.updateFailed')));
        }
    };

    const handleDeleteAccount = async (account: Account) => {
        if (!confirm(t('accounts.confirmDelete', { name: account.name }))) return;
        try {
            await api.delete(`/api/v1/accounts/${account.id}`);
            onDeleted(account.id);
        } catch (error) {
            console.error('Failed to delete account', error);
            onError(errorMessage(error, t('accounts.deleteFailed')));
        }
    };

    return (
        <>
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="glass-card p-6">
                    <h3 className="text-emerald-400 text-lg font-semibold mb-2">{t('accounts.myBalance')}</h3>
                    <p className="text-3xl font-bold">{money(totalBalance)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-sky-400 text-lg font-semibold mb-2">{t('accounts.title')}</h3>
                    <p className="text-3xl font-bold">{accounts.length}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-indigo-400 text-lg font-semibold mb-2">{t('accounts.transactionsInSelected')}</h3>
                    <p className="text-3xl font-bold">{transactionCount}</p>
                </div>
            </div>

            {/* Accounts Section */}
            <div className="glass-card p-6">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-xl font-bold">{t('accounts.title')}</h2>
                    <button onClick={() => setShowAddAccount(!showAddAccount)} className="btn-primary text-sm">
                        {t('accounts.add')}
                    </button>
                </div>

                {showAddAccount && (
                    <form onSubmit={handleAddAccount} className="mb-4 p-4 bg-slate-800/30 rounded-lg">
                        <input
                            type="text"
                            placeholder={t('accounts.namePlaceholder')}
                            value={newAccountName}
                            onChange={(e) => setNewAccountName(e.target.value)}
                            className={`${field} mb-2`}
                            required
                        />
                        <select value={newAccountType} onChange={(e) => setNewAccountType(e.target.value)} className={`${field} mb-2`}>
                            {ACCOUNT_TYPES.map(type => <option key={type} value={type}>{t(`accounts.types.${type}`)}</option>)}
                        </select>
                        <button type="submit" className="btn-primary w-full">{t('accounts.create')}</button>
                    </form>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {accounts.map(account => (
                        <div
                            key={account.id}
                            onClick={() => onSelect(account.id)}
                            className={`p-4 rounded-lg cursor-pointer transition-all ${selectedAccount === account.id
                                ? 'bg-blue-500/20 border-2 border-blue-400'
                                : 'bg-slate-800/30 border border-slate-700 hover:border-slate-600'
                                }`}
                        >
                            {editingAccount?.id === account.id ? (
                                <form onSubmit={handleSaveAccount} onClick={(e) => e.stopPropagation()} className="space-y-2">
                                    <input
                                        type="text"
                                        value={editingAccount.name}
                                        onChange={(e) => setEditingAccount({ ...editingAccount, name: e.target.value })}
                                        className={field}
                                        aria-label={t('accounts.name')}
                                        required
                                    />
                                    <select
                                        value={editingAccount.type}
                                        onChange={(e) => setEditingAccount({ ...editingAccount, type: e.target.value })}
                                        className={field}
                                        aria-label={t('accounts.type')}
                                    >
                                        {ACCOUNT_TYPES.map(type => <option key={type} value={type}>{t(`accounts.types.${type}`)}</option>)}
                                    </select>
                                    <div className="flex gap-2">
                                        <button type="submit" className="btn-primary text-sm flex-1">{t('common.save')}</button>
                                        <button type="button" onClick={() => setEditingAccount(null)} className="px-3 text-sm text-slate-400 hover:text-white">
                                            {t('common.cancel')}
                                        </button>
                                    </div>
                                </form>
                            ) : (<>
                                <h3 className="font-semibold text-lg">{account.name}</h3>
                                {account.user_id !== user?.id && ownerOf(account) && (
                                    <p className="text-xs text-slate-500">
                                        {ownerOf(account)!.username}{ownerOf(account)!.role === 'CHILD' ? t('accounts.ownAllowance') : ''}
                                    </p>
                                )}
                                <p className="text-sm text-slate-400">{t(`accounts.types.${account.type as typeof ACCOUNT_TYPES[number]}`)}</p>
                                <div className="flex justify-between items-end mt-2">
                                    <p className="text-2xl font-bold">{money(account.balance)}</p>
                                    {canEdit(account) && (
                                        <div className="flex gap-3">
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setEditingAccount({ id: account.id, name: account.name, type: account.type });
                                                }}
                                                className="text-sm text-slate-500 hover:text-blue-400 transition-colors"
                                                title={t('accounts.editTitle')}
                                            >
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDeleteAccount(account);
                                                }}
                                                className="text-sm text-slate-500 hover:text-red-400 transition-colors"
                                                title={t('accounts.deleteTitle')}
                                            >
                                                {t('common.delete')}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </>)}
                        </div>
                    ))}
                </div>
            </div>
        </>
    );
}
