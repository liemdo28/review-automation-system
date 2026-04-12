// Review Automation System — Dashboard JS

async function triggerSync(target) {
    try {
        await fetch(`/api/reviews/sync/${target}`, { method: 'POST' });
        alert(`Sync triggered for ${target === 'all' ? 'all locations' : target}. Reviews will appear shortly.`);
    } catch (e) {
        alert('Failed to trigger sync: ' + e.message);
    }
}

async function triggerFetch() { return triggerSync('all'); }

async function approveReply(reviewId) {
    const textarea = document.getElementById('replyText');
    const customText = textarea ? textarea.value.trim() : '';
    if (!confirm('Post this reply to Google Business Profile?')) return;
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(customText ? { reply_text: customText } : {}),
        });
        const data = await resp.json();
        if (data.status === 'approved_and_queued') {
            alert('Reply approved and queued for posting.');
            location.reload();
        } else {
            alert('Error: ' + JSON.stringify(data));
        }
    } catch (e) { alert('Failed to approve: ' + e.message); }
}

async function escalateReview(reviewId) {
    if (!confirm('Escalate this review to management?')) return;
    try {
        await fetch(`/api/reviews/${reviewId}/escalate`, { method: 'POST' });
        alert('Review escalated.');
        location.reload();
    } catch (e) { alert('Failed to escalate: ' + e.message); }
}

async function ignoreReview(reviewId) {
    if (!confirm('Mark this review as ignored?')) return;
    try {
        await fetch(`/api/reviews/${reviewId}/ignore`, { method: 'POST' });
        alert('Review marked as ignored.');
        location.reload();
    } catch (e) { alert('Failed: ' + e.message); }
}

async function markReplied(reviewId) {
    if (!confirm('Mark this review as manually replied?')) return;
    try {
        await fetch(`/api/reviews/${reviewId}/reply`, { method: 'POST' });
        alert('Marked as manually replied.');
        location.reload();
    } catch (e) { alert('Failed: ' + e.message); }
}

async function triggerAnalyze(reviewId) {
    try {
        await fetch(`/api/reviews/${reviewId}/analyze`, { method: 'POST' });
        alert('Analysis job queued. Refresh in a moment to see results.');
    } catch (e) { alert('Failed to trigger analysis: ' + e.message); }
}

async function triggerDraft(reviewId) {
    if (!confirm('Regenerate the AI reply draft? This will clear the existing analysis.')) return;
    try {
        await fetch(`/api/reviews/${reviewId}/draft`, { method: 'POST' });
        alert('Draft regeneration queued. Refresh in a moment.');
    } catch (e) { alert('Failed to regenerate: ' + e.message); }
}

function copyReply() {
    const textarea = document.getElementById('replyText');
    if (textarea) {
        navigator.clipboard.writeText(textarea.value)
            .then(() => alert('Reply copied to clipboard!'))
            .catch(() => { textarea.select(); document.execCommand('copy'); alert('Copied!'); });
    }
}
