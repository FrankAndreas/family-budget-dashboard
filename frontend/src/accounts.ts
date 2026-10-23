// Accounts and their transactions as the API returns them (Accounts tab)
import type { AttachmentInfo, Item } from './receipts';

export interface Account {
    id: string;
    user_id: string;
    name: string;
    type: string;
    balance: number;
    // Compact (CH9300762011623852957); a bank statement's lines find the account by it
    iban?: string | null;
}

// CH93 0076 2011 6238 5295 7
export const groupedIban = (iban: string) => iban.replace(/\s+/g, '').replace(/(.{4})(?=.)/g, '$1 ');

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
    // A receipt's items and the stored receipt files (issue #56)
    items?: Item[];
    attachments?: AttachmentInfo[];
}

export interface Category {
    id: string;
    name: string;
    type: string;
    icon?: string;
    // Set for the categories the app itself uses (TRANSFER, SETTLE_UP, ...): their name can't change
    system_key?: string | null;
}

// Labels: accounts.types.<value> in the locale files
export const ACCOUNT_TYPES = ['BANK', 'CASH', 'SAVINGS', 'CLEARING'] as const;
