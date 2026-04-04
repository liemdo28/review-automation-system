async function triggerFetch() {
    try {
        const resp = await fetch('/api/fetch/trigger', { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'fetch_triggered') {
            alert('Fetch cycle triggered! Reviews will appear shortly.');
        }
    } catch (e) {
        alert('Failed to trigger fetch: ' + e.message);
    }
}

async function approveReply(reviewId) {
    if (!confirm('Post this reply to Google Business Profile?')) return;
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/approve`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'queued') {
            alert('Reply approved and queued for posting.');
            location.reload();
        }
    } catch (e) {
        alert('Failed to approve: ' + e.message);
    }
}

function copyReply() {
    const textarea = document.getElementById('replyText');
    if (textarea) {
        navigator.clipboard.writeText(textarea.value);
        alert('Reply copied to clipboard!');
    }
}
