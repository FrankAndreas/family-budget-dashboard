import { useAuth } from '../../AuthContext';
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage, fetchAllTransactions } from '../../api';
import BudgetManager from '../../components/BudgetManager';
import Analytics from '../../components/Analytics';
import DataManager from '../../components/DataManager';
import FamilyManager from '../../components/FamilyManager';
import CategoryManager from '../../components/CategoryManager';
import ShareSettings from '../../components/ShareSettings';
import Logins from '../../components/Logins';
import CommonBudget from '../../components/CommonBudget';
import Investments from '../../components/Investments';
import YearlyBills from '../../components/YearlyBills';
import MonthCheck from '../../components/MonthCheck';
import Wishes from '../../components/Wishes';
import { useAssets, useSplits } from '../../finance';
import type { Account, Category, Transaction } from '../../accounts';
import AccountCards from '../../components/AccountCards';
import Transactions from '../../components/Transactions';
import { useFamily } from '../../useFamily';
import { accessTo, canWrite, dependents } from '../../family';

export default function Dashboard() {
    const { t } = useTranslation();
    const { user, logout } = useAuth();
    const { users, shares, reload: reloadFamily } = useFamily();
    const { splits, reload: reloadSplits } = useSplits();
    const { assets, reload: reloadAssets } = useAssets();
    const [activeTab, setActiveTab] = useState('overview');
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [error, setError] = useState('');
    // Bumped after any change to load accounts and the selected account's transactions again
    const [dataVersion, setDataVersion] = useState(0);
    const refresh = () => setDataVersion(v => v + 1);

    useEffect(() => {
        api.get('/api/v1/categories')
            .then(response => setCategories(response.data))
            .catch(error => {
                console.error('Failed to load categories', error);
                setError(errorMessage(error, t('dashboard.loadCategoriesFailed')));
            });
    }, [t]);

    useEffect(() => {
        api.get('/api/v1/accounts')
            .then(response => {
                const loaded: Account[] = response.data;
                setAccounts(loaded);
                // Keep the selection if that account still exists, otherwise pick the first one
                setSelectedAccount(prev =>
                    prev && loaded.some(a => a.id === prev) ? prev : loaded[0]?.id ?? null
                );
            })
            .catch(error => {
                console.error('Failed to load accounts', error);
                setError(errorMessage(error, t('dashboard.loadAccountsFailed')));
            });
    }, [dataVersion, t]);

    useEffect(() => {
        if (!selectedAccount) return;
        fetchAllTransactions<Transaction>(selectedAccount)
            .then(setTransactions)
            .catch(error => {
                console.error('Failed to load transactions', error);
                setError(errorMessage(error, t('dashboard.loadTransactionsFailed')));
            });
    }, [selectedAccount, dataVersion, t]);

    const ownerOf = (account: Account) => users.find(u => u.id === account.user_id);
    const canEdit = (account: Account) => !!user && canWrite(accessTo(user, account.user_id, users, shares));
    const selectedAccountObj = accounts.find(a => a.id === selectedAccount);
    // A deleted account's transactions stay loaded until another one is selected; don't show them
    const shownTransactions = selectedAccountObj ? transactions : [];
    const isParent = user?.role === 'PARENT';

    const tabs = [
        'overview', 'budgets', ...(isParent ? ['common', 'investments', 'bills'] as const : []), 'wishes', 'analytics', 'settings',
    ] as const;

    return (
        <div className="min-h-screen p-6">
            {/* Header */}
            <div className="glass-card p-6 mb-6">
                <div className="flex justify-between items-center">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-fuchsia-400 bg-clip-text text-transparent">
                            {t('common.appName')}
                        </h1>
                        <p className="text-slate-400 mt-1">
                            {t('dashboard.welcome', { name: user?.username, role: user ? t(`common.roles.${user.role}`) : '' })}
                        </p>
                    </div>
                    <button onClick={logout} className="btn-primary">
                        {t('dashboard.logout')}
                    </button>
                </div>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label={t('common.dismissError')}>✕</button>
                </div>
            )}

            {/* Tab Navigation */}
            <div className="glass-card p-2 mb-6">
                <div className="flex gap-2 overflow-x-auto">
                    {tabs.map(tab => (
                        <button
                            key={tab}
                            onClick={() => {
                                setActiveTab(tab);
                                // Other tabs may have changed the family, splits or investments the forms here offer
                                reloadFamily();
                                reloadSplits();
                                reloadAssets();
                            }}
                            className={`flex-1 whitespace-nowrap py-3 px-4 rounded-lg font-semibold transition-all ${activeTab === tab
                                ? 'bg-blue-500/20 text-blue-400 border-2 border-blue-400'
                                : 'text-slate-400 hover:bg-slate-800/30'
                                }`}
                        >
                            {t(`dashboard.tabs.${tab}`)}
                        </button>
                    ))}
                </div>
            </div>

            {/* Tab Content */}
            {activeTab === 'overview' && (
                <div className="space-y-6">
                    <AccountCards
                        accounts={accounts}
                        transactionCount={shownTransactions.length}
                        selectedAccount={selectedAccount}
                        onSelect={setSelectedAccount}
                        ownerOf={ownerOf}
                        canEdit={canEdit}
                        onChanged={refresh}
                        onDeleted={(accountId) => {
                            // Don't load the deleted account's transactions; the next account gets selected
                            if (accountId === selectedAccount) setSelectedAccount(null);
                            refresh();
                        }}
                        onError={setError}
                    />

                    {/* Clearing accounts (Migros, ...) should end every month at 0 */}
                    <MonthCheck
                        accounts={accounts.filter(a => a.type === 'CLEARING')}
                        canBook={canEdit}
                        version={dataVersion}
                        onBooked={refresh}
                    />

                    {selectedAccountObj && (
                        <Transactions
                            account={selectedAccountObj}
                            transactions={shownTransactions}
                            categories={categories}
                            canEdit={canEdit(selectedAccountObj)}
                            ownerName={ownerOf(selectedAccountObj)?.username}
                            isParentAccount={ownerOf(selectedAccountObj)?.role === 'PARENT'}
                            isParent={isParent}
                            children={dependents(users)}
                            splits={splits}
                            assets={assets}
                            onChanged={refresh}
                            onError={setError}
                        />
                    )}
                </div>
            )}

            {activeTab === 'budgets' && <BudgetManager />}
            {activeTab === 'common' && <CommonBudget />}
            {activeTab === 'investments' && <Investments />}
            {activeTab === 'bills' && <YearlyBills />}
            {activeTab === 'wishes' && <Wishes />}
            {activeTab === 'analytics' && <Analytics />}
            {activeTab === 'settings' && (
                <div className="space-y-6">
                    {user?.role === 'PARENT' && <FamilyManager />}
                    {user?.role === 'PARENT' && <CategoryManager />}
                    <ShareSettings />
                    <Logins />
                    <DataManager onDataChanged={refresh} />
                </div>
            )}
        </div>
    );
}
