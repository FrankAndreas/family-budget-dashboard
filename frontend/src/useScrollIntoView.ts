import { useEffect, useRef } from 'react';

// Brings a form above a long list into view when an entry starts being edited (key = its id), so editing an entry
// far down doesn't seem to do nothing
export function useScrollIntoView<T extends HTMLElement>(key: string | null | undefined) {
    const ref = useRef<T>(null);
    useEffect(() => {
        if (key) ref.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, [key]);
    return ref;
}
