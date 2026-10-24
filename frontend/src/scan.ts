// Receipts photographed on the phone (receipt scan): scaled down in the browser, then uploaded one at a time
import api from './api';
import type { InboxPhoto } from './inbox';

// A photo is shrunk in the browser before upload: receipts don't need more than 1600 px, and phone photos (3 to 8 MB)
// would come close to the 10 MB limit. Other files (PDF, e-mail) stay as they are.
const MAX_SIDE = 1600;

export async function shrink(file: File): Promise<Blob> {
    if (!file.type.startsWith('image/')) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return new Promise(resolve => canvas.toBlob(blob => resolve(blob ?? file), 'image/jpeg', 0.85));
}

export async function uploadPhoto(blob: Blob): Promise<InboxPhoto> {
    const body = new FormData();
    body.append('file', blob, 'scan.jpg');
    return (await api.post('/api/v1/inbox/photos', body)).data;
}
