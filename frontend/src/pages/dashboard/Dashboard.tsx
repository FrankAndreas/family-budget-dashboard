import { useAuth } from '../../AuthContext';
import { useState, useEffect } from 'react';
import api, { errorMessage, fetchAllTransactions } from '../../api';
import BudgetManager from '../../components/BudgetManager';
import Analytics from '../../components/Analytics';
import DataManager from '../../components/DataManager';
import FamilyManager from '../../components/FamilyManager';
import ShareSettings from '../../components/ShareSettings';
import CommonBudget from '../../components/CommonBudget';
import Investments from '../../components/Investments';
import YearlyBills from '../../components/YearlyBills';
import { useAssets, useSplits } from '../../finance';
import { useFamily } from '../../useFamily';
import { accessTo, canWrite, dependents } from '../../family';

interface Account {
    id: string;
    user_id: string;
    name: string;
    type: string;
    balance: number;
}

interface Transaction {
    id: string;
    amount: number;
    description: string;
    date: string;
    category_id: string;
    member_id?: string | null;
    split_id?: string | null;
    asset_id?: string | null;
}

interface Category {
    id: string;
    name: string;
    type: string;
    icon?: string;
}

export default function Dashboard() {
    const { user, logout } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const { assets } = useAssets();
    const [activeTab, setActiveTab] = useState('overview');
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [showAddAccount, setShowAddAccount] = useState(false);
    const [showAddTransaction, setShowAddTransaction] = useState(false);
    const [newAccountName, setNewAccountName] = useState('');
    const [newAccountType, setNewAccountType] = useState('BANK');
    const [newTransaction, setNewTransaction] = useState({
        amount: '',
        description: '',
        category_id: '',
        member_id: '',
        split_id: '',
        asset_id: ''
    });
    // Set while the transaction form is editing an existing transaction instead of adding one
    const [editingTransactionId, setEditingTransactionId] = useState<string | null>(null);
    const [error, setError] = useState('');
    // Account being renamed (inline form on its card)
    const [editingAccount, setEditingAccount] = useState<{ id: string; name: string; type: string } | null>(null);

    // Bumped after any change to load accounts and the selected account's transactions again
    const [dataVersion, setDataVersion] = useState(0);
    const refresh = () => setDataVersion(v => v + 1);

    useEffect(() => {
        api.get('/api/v1/categories')
            .then(response => setCategories(response.data))
            .catch(error => {
                console.error('Failed to load categories', error);
                setError(errorMessage(error, 'Failed to load categories'));
            });
    }, []);

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
                setError(errorMessage(error, 'Failed to load accounts'));
            });
    }, [dataVersion]);

    useEffect(() => {
        if (!selectedAccount) return;
        fetchAllTransactions<Transaction>(selectedAccount)
            .then(setTransactions)
            .catch(error => {
                console.error('Failed to load transactions', error);
                setError(errorMessage(error, 'Failed to load transactions'));
            });
    }, [selectedAccount, dataVersion]);

    const handleAddAccount = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/accounts', {
                name: newAccountName,
                type: newAccountType
            });
            setNewAccountName('');
            setShowAddAccount(false);
            refresh();
        } catch (error) {
            console.error('Failed to create account', error);
            setError(errorMessage(error, 'Failed to create account'));
        }
    };

    const handleSaveAccount = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingAccount) return;

        try {
            await api.put(`/api/v1/accounts/${editingAccount.id}`, {
                name: editingAccount.name,
                type: editingAccount.type
            });
            setEditingAccount(null);
            refresh();
        } catch (error) {
            console.error('Failed to update account', error);
            setError(errorMessage(error, 'Failed to update account'));
        }
    };

    const handleDeleteAccount = async (account: Account) => {
        if (!confirm(`Delete account "${account.name}" and all its transactions? This cannot be undone.`)) return;

        try {
            await api.delete(`/api/v1/accounts/${account.id}`);
            if (selectedAccount === account.id) {
                setTransactions([]);
            }
            refresh();
        } catch (error) {
            console.error('Failed to delete account', error);
            setError(errorMessage(error, 'Failed to delete account'));
        }
    };

    const closeTransactionForm = () => {
        setNewTransaction({ amount: '', description: '', category_id: '', member_id: '', split_id: '', asset_id: '' });
        setEditingTransactionId(null);
        setShowAddTransaction(false);
    };

    const handleEditTransaction = (transaction: Transaction) => {
        setNewTransaction({
            amount: Math.abs(transaction.amount).toString(),
            description: transaction.description || '',
            category_id: transaction.category_id,
            member_id: transaction.member_id || '',
            split_id: transaction.split_id || '',
            asset_id: transaction.asset_id || ''
        });
        setEditingTransactionId(transaction.id);
        setShowAddTransaction(true);
    };

    const handleSubmitTransaction = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!selectedAccount) return;

        const fields = {
            category_id: newTransaction.category_id,
            amount: parseFloat(newTransaction.amount),
            description: newTransaction.description,
            // null removes a tag when editing
            member_id: newTransaction.member_id || null,
            split_id: newTransaction.split_id || null,
            asset_id: newTransaction.asset_id || null
        };
        try {
            if (editingTransactionId) {
                await api.put(`/api/v1/transactions/${editingTransactionId}`, fields);
            } else {
                await api.post('/api/v1/transactions', { ...fields, account_id: selectedAccount });
            }
            closeTransactionForm();
            refresh();
        } catch (error) {
            console.error('Failed to save transaction', error);
            setError(errorMessage(error, 'Failed to save transaction'));
        }
    };

    const handleDeleteTransaction = async (transaction: Transaction) => {
        if (!selectedAccount) return;
        if (!confirm(`Delete "${transaction.description || 'No description'}" (${transaction.amount.toFixed(2)})?`)) return;

        try {
            await api.delete(`/api/v1/transactions/${transaction.id}`);
            refresh();
        } catch (error) {
            console.error('Failed to delete transaction', error);
            setError(errorMessage(error, 'Failed to delete transaction'));
        }
    };

    const ownerOf = (account: Account) => users.find(u => u.id === account.user_id);
    const isParentAccount = (account: Account) => ownerOf(account)?.role === 'PARENT';
    const canEdit = (account: Account) => !!user && canWrite(accessTo(user, account.user_id, users, shares));
    // Your own money; accounts others shared with you are listed but not added up
    const totalBalance = accounts.filter(a => a.user_id === user?.id).reduce((sum, acc) => sum + acc.balance, 0);
    const children = dependents(users);
    const memberName = (memberId?: string | null) => children.find(c => c.id === memberId)?.username;
    // A parent's expenses can be tagged with a child without own allowance
    const selectedAccountObj = accounts.find(a => a.id === selectedAccount);
    const canTagChild = !!selectedAccountObj && isParentAccount(selectedAccountObj) && children.length > 0;
    const canEditSelected = !!selectedAccountObj && canEdit(selectedAccountObj);
    const incomeCategories = categories.filter(c => c.type === 'INCOME');
    const expenseCategories = categories.filter(c => c.type === 'EXPENSE');
    const isExpense = (categoryId: string) => expenseCategories.some(c => c.id === categoryId);
    const isTransfer = (transaction: Transaction) =>
        categories.find(c => c.id === transaction.category_id)?.type === 'TRANSFER';
    const isParent = user?.role === 'PARENT';
    // Shared costs: a parent's expense divided with a split
    const canShare = isParent && !!selectedAccountObj && isParentAccount(selectedAccountObj) && splits.length > 0
        && isExpense(newTransaction.category_id);
    // Repairs, service, tyres... can be linked to an investment
    const canLinkItem = isParent && assets.length > 0 && isExpense(newTransaction.category_id);
    const assetName = (id?: string | null) => assets.find(a => a.id === id)?.name;

    const tabs = [
        { id: 'overview', label: '📊 Overview' },
        { id: 'budgets', label: '💰 Budgets' },
        ...(isParent ? [{ id: 'common', label: '🤝 Common' }, { id: 'investments', label: '📦 Investments' }, { id: 'bills', label: '🧾 Yearly bills' }] : []),
        { id: 'analytics', label: '📈 Analytics' },
        { id: 'settings', label: '⚙️ Settings' }
    ];

    return (
        <div className="min-h-screen p-6">
            {/* Header */}
            <div className="glass-card p-6 mb-6">
                <div className="flex justify-between items-center">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-fuchsia-400 bg-clip-text text-transparent">
                            Family Budget
                        </h1>
                        <p className="text-slate-400 mt-1">Welcome back, {user?.username} ({user?.role})</p>
                    </div>
                    <button onClick={logout} className="btn-primary">
                        Logout
                    </button>
                </div>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label="Dismiss error">✕</button>
                </div>
            )}

            {/* Tab Navigation */}
            <div className="glass-card p-2 mb-6">
                <div className="flex gap-2 overflow-x-auto">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex-1 whitespace-nowrap py-3 px-4 rounded-lg font-semibold transition-all ${activeTab === tab.id
                                ? 'bg-blue-500/20 text-blue-400 border-2 border-blue-400'
                                : 'text-slate-400 hover:bg-slate-800/30'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Tab Content */}
            {activeTab === 'overview' && (
                <div className="space-y-6">
                    {/* Summary Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="glass-card p-6">
                            <h3 className="text-emerald-400 text-lg font-semibold mb-2">My Balance</h3>
                            <p className="text-3xl font-bold">${totalBalance.toFixed(2)}</p>
                        </div>
                        <div className="glass-card p-6">
                            <h3 className="text-sky-400 text-lg font-semibold mb-2">Accounts</h3>
                            <p className="text-3xl font-bold">{accounts.length}</p>
                        </div>
                        <div className="glass-card p-6">
                            <h3 className="text-indigo-400 text-lg font-semibold mb-2">Transactions in Selected Account</h3>
                            <p className="text-3xl font-bold">{transactions.length}</p>
                        </div>
                    </div>

                    {/* Accounts Section */}
                    <div className="glass-card p-6">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-xl font-bold">Accounts</h2>
                            <button
                                onClick={() => setShowAddAccount(!showAddAccount)}
                                className="btn-primary text-sm"
                            >
                                + Add Account
                            </button>
                        </div>

                        {showAddAccount && (
                            <form onSubmit={handleAddAccount} className="mb-4 p-4 bg-slate-800/30 rounded-lg">
                                <input
                                    type="text"
                                    placeholder="Account Name"
                                    value={newAccountName}
                                    onChange={(e) => setNewAccountName(e.target.value)}
                                    className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                    required
                                />
                                <select
                                    value={newAccountType}
                                    onChange={(e) => setNewAccountType(e.target.value)}
                                    className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                >
                                    <option value="BANK">Bank Account</option>
                                    <option value="CASH">Cash</option>
                                    <option value="SAVINGS">Savings</option>
                                </select>
                                <button type="submit" className="btn-primary w-full">Create Account</button>
                            </form>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {accounts.map(account => (
                                <div
                                    key={account.id}
                                    onClick={() => setSelectedAccount(account.id)}
                                    className={`p-4 rounded-lg cursor-pointer transition-all ${selectedAccount === account.id
                                        ? 'bg-blue-500/20 border-2 border-blue-400'
                                        : 'bg-slate-800/30 border border-slate-700 hover:border-slate-600'
                                        }`}
                                >
                                    {editingAccount?.id === account.id ? (
                                        <form
                                            onSubmit={handleSaveAccount}
                                            onClick={(e) => e.stopPropagation()}
                                            className="space-y-2"
                                        >
                                            <input
                                                type="text"
                                                value={editingAccount.name}
                                                onChange={(e) => setEditingAccount({ ...editingAccount, name: e.target.value })}
                                                className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                                aria-label="Account name"
                                                required
                                            />
                                            <select
                                                value={editingAccount.type}
                                                onChange={(e) => setEditingAccount({ ...editingAccount, type: e.target.value })}
                                                className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                                aria-label="Account type"
                                            >
                                                <option value="BANK">Bank Account</option>
                                                <option value="CASH">Cash</option>
                                                <option value="SAVINGS">Savings</option>
                                            </select>
                                            <div className="flex gap-2">
                                                <button type="submit" className="btn-primary text-sm flex-1">Save</button>
                                                <button type="button" onClick={() => setEditingAccount(null)} className="px-3 text-sm text-slate-400 hover:text-white">
                                                    Cancel
                                                </button>
                                            </div>
                                        </form>
                                    ) : (<>
                                    <h3 className="font-semibold text-lg">{account.name}</h3>
                                    {account.user_id !== user?.id && ownerOf(account) && (
                                        <p className="text-xs text-slate-500">
                                            {ownerOf(account)!.username}{ownerOf(account)!.role === 'CHILD' ? ' (own allowance)' : ''}
                                        </p>
                                    )}
                                    <p className="text-sm text-slate-400">{account.type}</p>
                                    <div className="flex justify-between items-end mt-2">
                                        <p className="text-2xl font-bold">${account.balance.toFixed(2)}</p>
                                        {canEdit(account) && (
                                            <div className="flex gap-3">
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setEditingAccount({ id: account.id, name: account.name, type: account.type });
                                                    }}
                                                    className="text-sm text-slate-500 hover:text-blue-400 transition-colors"
                                                    title="Edit account"
                                                >
                                                    Edit
                                                </button>
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleDeleteAccount(account);
                                                    }}
                                                    className="text-sm text-slate-500 hover:text-red-400 transition-colors"
                                                    title="Delete account"
                                                >
                                                    Delete
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                    </>)}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Transactions Section */}
                    {selectedAccount && (
                        <div className="glass-card p-6">
                            <div className="flex justify-between items-center mb-4">
                                <h2 className="text-xl font-bold">Transactions</h2>
                                {canEditSelected && (
                                <button
                                    onClick={() => showAddTransaction ? closeTransactionForm() : setShowAddTransaction(true)}
                                    className="btn-primary text-sm"
                                >
                                    + Add Transaction
                                </button>
                                )}
                            </div>

                            {!canEditSelected && selectedAccountObj && (
                                <p className="text-sm text-slate-400 mb-3">
                                    Read only: {ownerOf(selectedAccountObj)?.username ?? 'the owner'} shared this account with you to view.
                                </p>
                            )}

                            {showAddTransaction && canEditSelected && (
                                <form onSubmit={handleSubmitTransaction} className="mb-4 p-4 bg-slate-800/30 rounded-lg">
                                    <input
                                        type="number"
                                        step="0.01"
                                        min="0.01"
                                        placeholder="Amount (income or expense is set by the category)"
                                        value={newTransaction.amount}
                                        onChange={(e) => setNewTransaction({ ...newTransaction, amount: e.target.value })}
                                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        required
                                    />
                                    <input
                                        type="text"
                                        placeholder="Description"
                                        value={newTransaction.description}
                                        onChange={(e) => setNewTransaction({ ...newTransaction, description: e.target.value })}
                                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                    />
                                    <select
                                        value={newTransaction.category_id}
                                        onChange={(e) => setNewTransaction({
                                            ...newTransaction,
                                            category_id: e.target.value,
                                            // Only expenses can be shared
                                            split_id: isExpense(e.target.value) ? newTransaction.split_id : '',
                                            asset_id: isExpense(e.target.value) ? newTransaction.asset_id : ''
                                        })}
                                        className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        required
                                    >
                                        <option value="">Select Category</option>
                                        <optgroup label="Income">
                                            {incomeCategories.map(cat => (
                                                <option key={cat.id} value={cat.id}>{cat.name}</option>
                                            ))}
                                        </optgroup>
                                        <optgroup label="Expenses">
                                            {expenseCategories.map(cat => (
                                                <option key={cat.id} value={cat.id}>{cat.name}</option>
                                            ))}
                                        </optgroup>
                                    </select>
                                    {canTagChild && (
                                        <select
                                            value={newTransaction.member_id}
                                            onChange={(e) => setNewTransaction({ ...newTransaction, member_id: e.target.value })}
                                            className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                            aria-label="For child"
                                        >
                                            <option value="">For: no child</option>
                                            {children.map(child => (
                                                <option key={child.id} value={child.id}>For: {child.username}</option>
                                            ))}
                                        </select>
                                    )}
                                    {canShare && (
                                        <select
                                            value={newTransaction.split_id}
                                            onChange={(e) => setNewTransaction({ ...newTransaction, split_id: e.target.value })}
                                            className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                            aria-label="Shared"
                                        >
                                            <option value="">Shared: not shared</option>
                                            {splits.map(split => (
                                                <option key={split.id} value={split.id}>Shared: {split.name}</option>
                                            ))}
                                        </select>
                                    )}
                                    {canLinkItem && (
                                        <select
                                            value={newTransaction.asset_id}
                                            onChange={(e) => setNewTransaction({ ...newTransaction, asset_id: e.target.value })}
                                            className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                            aria-label="For item"
                                        >
                                            <option value="">For item: none</option>
                                            {assets.map(asset => (
                                                <option key={asset.id} value={asset.id}>For item: {asset.name}</option>
                                            ))}
                                        </select>
                                    )}
                                    <div className="flex gap-2">
                                        <button type="submit" className="btn-primary flex-1">
                                            {editingTransactionId ? 'Save Changes' : 'Add Transaction'}
                                        </button>
                                        {editingTransactionId && (
                                            <button type="button" onClick={closeTransactionForm} className="px-4 text-slate-400 hover:text-white">
                                                Cancel
                                            </button>
                                        )}
                                    </div>
                                </form>
                            )}

                            <div className="space-y-2">
                                {transactions.length === 0 ? (
                                    <p className="text-slate-400 text-center py-8">No transactions yet</p>
                                ) : (
                                    transactions.map(transaction => (
                                        <div key={transaction.id} className="p-3 bg-slate-800/30 rounded-lg flex justify-between items-center">
                                            <div>
                                                <p className="font-semibold">
                                                    {transaction.description || 'No description'}
                                                    {memberName(transaction.member_id) && (
                                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                                                            for {memberName(transaction.member_id)}
                                                        </span>
                                                    )}
                                                    {assetName(transaction.asset_id) && (
                                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                                                            {assetName(transaction.asset_id)}
                                                        </span>
                                                    )}
                                                    {transaction.split_id && (
                                                        <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300">
                                                            shared
                                                        </span>
                                                    )}
                                                </p>
                                                <p className="text-sm text-slate-400">{new Date(transaction.date).toLocaleDateString()}</p>
                                            </div>
                                            <div className="flex items-center gap-3">
                                                <p className={`text-xl font-bold ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                    {transaction.amount >= 0 ? '+' : ''} ${transaction.amount.toFixed(2)}
                                                </p>
                                                {canEditSelected && !isTransfer(transaction) && (<>
                                                <button
                                                    onClick={() => handleEditTransaction(transaction)}
                                                    className="text-slate-500 hover:text-blue-400 transition-colors"
                                                    title="Edit transaction"
                                                    aria-label="Edit transaction"
                                                >
                                                    ✎
                                                </button>
                                                <button
                                                    onClick={() => handleDeleteTransaction(transaction)}
                                                    className="text-slate-500 hover:text-red-400 transition-colors"
                                                    title="Delete transaction"
                                                    aria-label="Delete transaction"
                                                >
                                                    ✕
                                                </button>
                                                </>)}
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'budgets' && <BudgetManager />}
            {activeTab === 'common' && <CommonBudget />}
            {activeTab === 'investments' && <Investments />}
            {activeTab === 'bills' && <YearlyBills />}
            {activeTab === 'analytics' && <Analytics />}
            {activeTab === 'settings' && (
                <div className="space-y-6">
                    {user?.role === 'PARENT' && <FamilyManager />}
                    <ShareSettings />
                    <DataManager />
                </div>
            )}
        </div>
    );
}
