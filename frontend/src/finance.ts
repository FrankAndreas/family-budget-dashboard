import { useCallback, useEffect, useState } from 'react';
import api from './api';

export interface Split {
    id: string;
    name: string;
    // Percent per parent id
    shares: Record<string, number>;
}

export interface Overview {
    items: { kind: 'planned' | 'asset'; id: string; name: string; monthly: number; shares: Record<string, number> }[];
    totals: Record<string, number>;
}

// Swiss francs, the same text in every browser: CHF 1'234.50, CHF -22.10 (Intl's output differs between browsers)
export function money(value: number): string {
    const cents = Math.round(value * 100);
    const francs = Math.floor(Math.abs(cents) / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
    const rest = (Math.abs(cents) % 100).toString().padStart(2, '0');
    return `CHF ${cents < 0 ? '-' : ''}${francs}.${rest}`;
}

export const describeSplit = (split: Split, nameOf: (id: string) => string) =>
    Object.entries(split.shares).map(([id, percent]) => `${nameOf(id)} ${percent}%`).join(' / ');

// The parents' preset splits (empty for children, who can't use them)
export function useSplits() {
    const [splits, setSplits] = useState<Split[]>([]);
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/splits')
            .then(response => setSplits(response.data))
            .catch(() => setSplits([]));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);
    return { splits, reload };
}

export interface Asset {
    id: string;
    name: string;
    price: number;
    purchase_date: string;
    lifespan_years: number;
    owner_id: string | null;
    split_id: string | null;
    notes: string | null;
    age_years: number;
    // Purchase date in the future: not bought yet
    planned: boolean;
    replacement_due: string;
    is_due: boolean;
    monthly_set_aside: number;
    total_cost: number;
    cost_per_year: number;
    shares: Record<string, number>;
}

// Investments the current parent can see (empty for children)
export function useAssets() {
    const [assets, setAssets] = useState<Asset[]>([]);
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/assets')
            .then(response => setAssets(response.data))
            .catch(() => setAssets([]));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);
    return { assets, reload };
}

export interface PlannedCost {
    id: string;
    name: string;
    category_id: string;
    amount: number;
    frequency: 'MONTHLY' | 'YEARLY';
    due_month: number | null;
    owner_id: string | null;
    split_id: string | null;
    notes: string | null;
    monthly: number;
    next_due: string | null;
    due_soon: boolean;
    // Monthly amount per person
    shares: Record<string, number>;
}

export const MONTHS = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
];
