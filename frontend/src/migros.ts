// Migros receipts from the Cumulus CSV export ("Kassenbeleg"): recognised by its header, previewed and imported by
// MigrosImport (spec 2026-10-28)

const HEADER = 'datum;zeit;filiale;kassennummer;transaktionsnummer;artikel;menge;aktion;umsatz';

export async function isMigrosFile(file: File): Promise<boolean> {
    const start = await file.slice(0, 200).text();
    return start.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0].trim().toLowerCase() === HEADER;
}

export type ArticleSource = 'change' | 'rule' | 'ai' | 'fallback';

export interface Article { category_id: string; tag_ids: string[]; source: ArticleSource }

// key: the article as the server compares it (its articles are keyed by it)
export interface ReceiptLine { key: string; name: string; amount: number; category_id: string; tag_ids: string[]; source: ArticleSource | 'discount' }

export interface MigrosReceipt {
    key: string;
    date: string;
    time: string;
    store: string;
    total: number;
    status: 'new' | 'imported' | 'maybe_booked' | 'error';
    error: string | null;
    include: boolean;
    payments: { id: string; description: string | null; date: string; amount: number }[];
    payment: string;
    account_id: string | null;
    lines: ReceiptLine[];
}

export interface MigrosPreview {
    receipts: MigrosReceipt[];
    articles: Record<string, Article>;
    accounts: { id: string; name: string }[];
    // Articles the import will propose as rules (Settings → Article rules)
    new_suggestions: number;
    ai: { status: 'off' | 'ok' | 'capped' | 'limit' | 'failed'; message: string | null } | null;
}

export interface ReceiptChoice { include: boolean; payment: string; account_id: string | null }

// "2026-09-12" → "12.09.2026", as on the receipt (names the receipt in labels)
export const receiptDay = (iso: string) => iso.split('-').reverse().join('.');

// What the server expects back: the articles as shown, and only what the person changed on receipts, so the
// payments the person didn't choose can move to fit theirs
export const migrosForm = (file: File, articles: Record<string, Article>, receipts: Record<string, Partial<ReceiptChoice>>, ai = false) => {
    const data = new FormData();
    data.append('file', file);
    data.append('choices', JSON.stringify({ articles, receipts }));
    if (ai) data.append('ai', '1');
    return data;
};
