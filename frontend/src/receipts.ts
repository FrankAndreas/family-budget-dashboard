// Receipts (issue #56): bookings with items, tags, attachments, and reading a receipt with the AI
import { useCallback, useEffect, useState } from 'react';
import api from './api';

export interface Tag {
    id: string;
    name: string;
    icon?: string | null;
}

export interface Item {
    id?: string;
    name: string;
    amount: number;
    category_id: string;
    person_id?: string | null;
    tag_ids: string[];
    // A line of the AI's draft whose category and tags come from an article rule
    source?: 'rule';
}

export interface AttachmentInfo {
    id: string;
    filename: string;
    content_type: string;
    size: number;
}

// What the AI read; nothing is booked until the person saves it
export interface Draft {
    shop: string;
    date: string;
    total: number | null;
    items: Item[];
    difference: number;
}

export function useTags() {
    const [tags, setTags] = useState<Tag[]>([]);
    const [version, setVersion] = useState(0);
    useEffect(() => {
        api.get('/api/v1/tags')
            .then(response => setTags(response.data))
            .catch(error => console.error('Failed to load tags', error));
    }, [version]);
    const reload = useCallback(() => setVersion(v => v + 1), []);
    return { tags, reload };
}

// Whether reading receipts with the AI is set up on the server
export function useReceiptReading(): boolean {
    const [enabled, setEnabled] = useState(false);
    useEffect(() => {
        api.get('/api/v1/receipts/status')
            .then(response => setEnabled(response.data.enabled))
            .catch(() => setEnabled(false));
    }, []);
    return enabled;
}

// An attachment opened in a new tab (images, PDFs) or downloaded (e-mails); the request carries the login
export async function openAttachment(attachment: AttachmentInfo) {
    const response = await api.get(`/api/v1/attachments/${attachment.id}`, { responseType: 'blob' });
    const url = URL.createObjectURL(response.data);
    if (attachment.content_type === 'message/rfc822') {
        const link = document.createElement('a');
        link.href = url;
        link.download = attachment.filename;
        link.click();
    } else {
        window.open(url, '_blank', 'noopener');
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
