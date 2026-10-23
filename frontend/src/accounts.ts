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
    // Reconciliation: open bookings and bank lines, and the sum of the bookings the bank hasn't confirmed
    open_points?: number;
    not_confirmed?: number;
}

// A line of an imported bank statement
export interface BankRow {
    id: string;
    booked_on: string;
    valuta_on?: string | null;
    text: string;
    amount: number;
    transaction_id?: string | null;
}

// Whether the bank confirmed a booking (null before the account's first statement, and on cash accounts)
export interface BookingState {
    confirmation: 'confirmed' | 'partly_paid' | 'not_confirmed' | 'no_payment' | null;
    receipt_missing: boolean;
    differs: boolean;
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
    // The bank lines that paid it, and its state (bank import, part 2)
    bank_rows?: BankRow[];
    receipt_expected?: boolean;
    difference?: number | null;
    difference_accepted?: boolean;
    state?: BookingState | null;
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
