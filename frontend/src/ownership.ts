// Who an investment or yearly bill belongs to, as one select value: "owner:<user id>" or "split:<split id>"

export function ownerFields(value: string): { owner_id: string | null; split_id: string | null } {
    const [kind, id] = value.split(':');
    return kind === 'split' ? { owner_id: null, split_id: id } : { owner_id: id, split_id: null };
}

export function ownerValue(item: { owner_id: string | null; split_id: string | null }): string {
    return item.split_id ? `split:${item.split_id}` : `owner:${item.owner_id}`;
}
