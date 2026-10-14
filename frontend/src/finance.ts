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

// Same money format as the rest of the app
export function money(value: number): string {
    return `$${value.toFixed(2)}`;
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
