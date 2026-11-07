import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage, fetchAllTransactions } from '../api';
import { useAuth } from '../AuthContext';
import { money } from '../finance';
import { ACCOUNT_TYPES, groupedIban, type Account } from '../accounts';
import type { FamilyUser } from '../family';
import { ask } from '../confirm';

interface Props {
    accounts: Account[];
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

// The account cards, with adding, renaming and deleting accounts
export default function AccountCards({
    accounts, selectedAccount, onSelect, ownerOf, canEdit, onChanged, onDeleted, onError
}: Props) {
    const { t } = useTranslation();
    const { user } = useAuth();
    const [showAddAccount, setShowAddAccount] = useState(false);
    const [newAccountName, setNewAccountName] = useState('');
    const [newAccountType, setNewAccountType] = useState('BANK');
    const [newAccountIban, setNewAccountIban] = useState('');
    // Account being renamed (inline form on its card)
    const [editingAccount, setEditingAccount] = useState<{ id: string; name: string; type: string; iban: string } | null>(null);
    // Only parents enter IBANs (the bank import finds accounts by them)
    const isParent = user?.role === 'PARENT';

    const handleAddAccount = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/accounts', {
                name: newAccountName, type: newAccountType, ...(isParent && newAccountIban ? { iban: newAccountIban } : {}),
            });
            setNewAccountName('');
            setNewAccountIban('');
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
            await api.put(`/api/v1/accounts/${editingAccount.id}`, {
                name: editingAccount.name, type: editingAccount.type, ...(isParent ? { iban: editingAccount.iban } : {}),
            });
            setEditingAccount(null);
            onChanged();
        } catch (error) {
            console.error('Failed to update account', error);
            onError(errorMessage(error, t('accounts.updateFailed')));
        }
    };

    const handleDeleteAccount = async (account: Account) => {
        // Say what goes with it: the account's bookings are deleted too
        let count: number;
        try {
            count = (await fetchAllTransactions(account.id)).length;
        } catch {
            count = -1;
        }
        const message = count < 0 ? t('accounts.confirmDelete', { name: account.name })
            : count === 0 ? t('accounts.confirmDeleteEmpty', { name: account.name })
                : t('accounts.confirmDeleteWithBookings', { name: account.name, count });
        if (!await ask(message)) return;
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
            {/* Accounts Section */}
            <div className="glass-card p-6">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-xl font-bold">{t('accounts.title')}</h2>
                    <button onClick={() => setShowAddAccount(!showAddAccount)} className="btn-secondary text-sm">
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
                        {isParent && (
                            <input
                                type="text"
                                placeholder={t('accounts.ibanPlaceholder')}
                                value={newAccountIban}
                                onChange={(e) => setNewAccountIban(e.target.value)}
                                className={`${field} mb-2`}
                                aria-label={t('accounts.iban')}
                            />
                        )}
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
                                    {isParent && (
                                        <input
                                            type="text"
                                            placeholder={t('accounts.ibanPlaceholder')}
                                            value={editingAccount.iban}
                                            onChange={(e) => setEditingAccount({ ...editingAccount, iban: e.target.value })}
                                            className={field}
                                            aria-label={t('accounts.iban')}
                                        />
                                    )}
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
                                {isParent && account.iban && <p className="text-xs text-slate-500 font-mono">{groupedIban(account.iban)}</p>}
                                {(account.not_confirmed ?? 0) !== 0 && (
                                    <p className="text-xs text-slate-400">{t('reconcile.ofWhichNotConfirmed', { amount: money(account.not_confirmed ?? 0) })}</p>
                                )}
                                {(account.open_points ?? 0) > 0 && (
                                    <p className="text-xs text-amber-300">{t('reconcile.openPoints', { count: account.open_points })}</p>
                                )}
                                <div className="flex justify-between items-end mt-2">
                                    <p className="text-2xl font-bold">{money(account.balance)}</p>
                                    {canEdit(account) && (
                                        <div className="flex gap-3">
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setEditingAccount({ id: account.id, name: account.name, type: account.type, iban: account.iban ? groupedIban(account.iban) : '' });
                                                }}
                                                className="link-edit"
                                                title={t('accounts.editTitle')}
                                            >
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDeleteAccount(account);
                                                }}
                                                className="link-delete"
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
