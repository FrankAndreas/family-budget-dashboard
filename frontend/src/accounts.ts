// Accounts and their transactions as the API returns them (Accounts tab)

export interface Account {
    id: string;
    user_id: string;
    name: string;
    type: string;
    balance: number;
}

export interface Transaction {
    id: string;
    amount: number;
    description: string;
    date: string;
    category_id: string;
    member_id?: string | null;
    split_id?: string | null;
    // The percentages a shared expense was booked with (kept when its split is deleted)
    split_shares?: Record<string, number> | null;
    asset_id?: string | null;
}

export interface Category {
    id: string;
    name: string;
    type: string;
    icon?: string;
}

export const ACCOUNT_TYPES = [
    { value: 'BANK', label: 'Bank Account' },
    { value: 'CASH', label: 'Cash' },
    { value: 'SAVINGS', label: 'Savings' },
    { value: 'CLEARING', label: 'Clearing (Migros, …)' },
];
