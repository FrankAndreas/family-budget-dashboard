import { useState } from 'react';

const WIDE = '(min-width: 768px)';

function initiallyOpen(key: string, wide: boolean): boolean {
    try {
        const stored = localStorage.getItem(key);
        if (stored !== null) return stored === '1';
    } catch {
        // No storage (private window): the default below
    }
    return wide && (window.matchMedia?.(WIDE).matches ?? true);
}

// Whether a fold is open, remembered in this browser under key; first folded on a phone, on a wider screen open
// unless openOnWide is false
export function useRememberedOpen(key: string, openOnWide = true) {
    const [open, setOpen] = useState(() => initiallyOpen(key, openOnWide));
    const toggle = (event: React.SyntheticEvent<HTMLDetailsElement>) => {
        const now = event.currentTarget.open;
        setOpen(now);
        try {
            localStorage.setItem(key, now ? '1' : '0');
        } catch {
            // Not remembered: fine
        }
    };
    return { open, toggle };
}
