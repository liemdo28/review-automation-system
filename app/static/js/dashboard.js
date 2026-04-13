async function triggerFetch(query = "") {
    try {
        const suffix = query ? `?${query}` : "";
        const resp = await fetch(`/api/fetch/trigger${suffix}`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "fetch_triggered") {
            alert("Sync started. Updated reviews should appear shortly.");
        }
    } catch (error) {
        alert("Failed to start sync: " + error.message);
    }
}

async function launchSessionBootstrap(sourceId, sourceLabel = "source", platform = "source") {
    try {
        const resp = await fetch(`/api/sources/${sourceId}/bootstrap`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Bootstrap launch failed.");
        }
        alert(
            `Login window opened for ${sourceLabel} (${platform}). Sign in there, stay on the correct review page, then press ENTER in the START login window to save that session.`,
        );
    } catch (error) {
        alert("Failed to launch login bootstrap: " + error.message);
    }
}

async function approveReply(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/approve`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "queued") {
            alert("Reply approved. Operator-assisted posting has been queued.");
            location.reload();
        }
    } catch (error) {
        alert("Failed to approve reply: " + error.message);
    }
}

async function regenerateReply(reviewId) {
    const toneMode = prompt(
        "Tone mode: gentle_professional, warm_hospitality, or premium_brand",
        "gentle_professional",
    );
    if (!toneMode) return;

    try {
        const params = new URLSearchParams({ tone_mode: toneMode });
        const resp = await fetch(`/api/reviews/${reviewId}/suggestions/regenerate?${params.toString()}`, {
            method: "POST",
        });
        const data = await resp.json();
        if (data.status === "ok") {
            alert("Suggestion regenerated.");
            location.reload();
        }
    } catch (error) {
        alert("Failed to regenerate suggestion: " + error.message);
    }
}

function copyReply() {
    const textarea = document.getElementById("replyText");
    if (!textarea) return;
    navigator.clipboard.writeText(textarea.value);
    alert("Reply copied to clipboard.");
}

function selectedReviewIds() {
    return Array.from(document.querySelectorAll(".review-select:checked")).map((input) => Number(input.value));
}

function toggleAllReviews(checked) {
    document.querySelectorAll(".review-select").forEach((input) => {
        input.checked = checked;
    });
    const master = document.getElementById("selectAllReviews");
    if (master) master.checked = checked;
}

async function bulkRegenerate() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        alert("Select at least one review first.");
        return;
    }
    const toneMode = prompt(
        "Tone mode for selected reviews: gentle_professional, warm_hospitality, or premium_brand",
        "gentle_professional",
    );
    if (!toneMode) return;

    const resp = await fetch("/api/reviews/bulk/regenerate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_ids: reviewIds, tone_mode: toneMode, handled_by: "operator" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
        alert(`Regenerated ${data.updated_reviews} review suggestion(s).`);
        location.reload();
    }
}

async function bulkMarkHandled() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        alert("Select at least one review first.");
        return;
    }
    const resp = await fetch("/api/reviews/bulk/mark-handled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_ids: reviewIds, handled_by: "operator" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
        alert(`Marked ${data.updated_reviews} review(s) as handled.`);
        location.reload();
    }
}

function bulkExport() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        alert("Select at least one review first.");
        return;
    }
    const params = new URLSearchParams({ review_ids: reviewIds.join(",") });
    window.open(`/api/reviews/export/selected.csv?${params.toString()}`, "_blank");
}

async function markSingleHandled(reviewId) {
    const resp = await fetch("/api/reviews/bulk/mark-handled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_ids: [reviewId], handled_by: "operator" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
        alert("Review marked as handled.");
        location.reload();
    }
}
