function showToast(message, type = "info") {
    const stack = document.getElementById("toastStack");
    if (!stack) {
        return;
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    stack.appendChild(toast);

    window.setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-6px)";
    }, 3000);
    window.setTimeout(() => toast.remove(), 3400);
}

async function triggerFetch(query = "") {
    try {
        const suffix = query ? `?${query}` : "";
        const resp = await fetch(`/api/fetch/trigger${suffix}`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "fetch_triggered") {
            showToast("Sync started. Updated reviews should appear shortly.", "success");
        }
    } catch (error) {
        showToast("Failed to start sync: " + error.message, "error");
    }
}

async function launchSessionBootstrap(sourceId, sourceLabel = "source", platform = "source") {
    try {
        const resp = await fetch(`/api/sources/${sourceId}/bootstrap`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Bootstrap launch failed.");
        }
        showToast(
            `Login window opened for ${sourceLabel} (${platform}). Sign in there, open the exact review page for that source, then press ENTER in the START login window. START will save both the session and the exact review URL for that source when it can detect it.`,
            "info",
        );
    } catch (error) {
        showToast("Failed to launch login bootstrap: " + error.message, "error");
    }
}

async function launchSharedPlatformLogin(sourceId, platform = "source") {
    try {
        const resp = await fetch(`/api/sources/${sourceId}/bootstrap?share_scope=platform`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Shared login launch failed.");
        }
        showToast(
            `Shared ${platform} login window opened. Sign in once, keep the review page open, then press ENTER in the START login window. START will apply that session to all ${platform} sources.`,
            "info",
        );
    } catch (error) {
        showToast("Failed to launch shared login: " + error.message, "error");
    }
}

async function approveReply(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/approve`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "queued") {
            showToast("Reply approved for manual posting (no automation).", "success");
            location.reload();
        }
    } catch (error) {
        showToast("Failed to approve reply: " + error.message, "error");
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
            showToast("Suggestion regenerated.", "success");
            location.reload();
        }
    } catch (error) {
        showToast("Failed to regenerate suggestion: " + error.message, "error");
    }
}

function copyReply() {
    const textarea = document.getElementById("replyText");
    if (!textarea) return;
    navigator.clipboard.writeText(textarea.value);
    showToast("Reply copied to clipboard.", "success");
}

const reviewSelection = new Set();
let autoReplyPreviewState = null;

function selectedReviewIds() {
    return Array.from(reviewSelection.values());
}

function updateSelectionUi() {
    const count = reviewSelection.size;
    const countText = `${count} review${count === 1 ? "" : "s"} selected`;
    const summary = document.getElementById("bulkActionSummary");
    const countNode = document.getElementById("selectedReviewCount");
    const bulkBar = document.getElementById("bulkActionBar");
    if (summary) summary.textContent = countText;
    if (countNode) countNode.textContent = countText;
    if (bulkBar) bulkBar.classList.toggle("is-hidden", count === 0);
}

function syncCheckboxesFromSelection() {
    document.querySelectorAll(".review-select").forEach((input) => {
        input.checked = reviewSelection.has(Number(input.value));
    });
    const master = document.getElementById("selectAllReviews");
    if (master) {
        const visibleIds = Array.from(document.querySelectorAll(".review-select")).map((input) => Number(input.value));
        master.checked = visibleIds.length > 0 && visibleIds.every((id) => reviewSelection.has(id));
    }
}

function syncReviewSelection() {
    document.querySelectorAll(".review-select").forEach((input) => {
        const reviewId = Number(input.value);
        if (input.checked) {
            reviewSelection.add(reviewId);
        } else {
            reviewSelection.delete(reviewId);
        }
    });
    updateSelectionUi();
}

function toggleCurrentPageSelection(checked) {
    document.querySelectorAll(".review-select").forEach((input) => {
        input.checked = checked;
        const reviewId = Number(input.value);
        if (checked) {
            reviewSelection.add(reviewId);
        } else {
            reviewSelection.delete(reviewId);
        }
    });
    const master = document.getElementById("selectAllReviews");
    if (master) master.checked = checked;
    updateSelectionUi();
}

async function toggleFilteredSelection(checked) {
    if (!checked) {
        clearReviewSelection();
        return;
    }
    try {
        const params = new URLSearchParams(window.location.search);
        const resp = await fetch(`/api/reviews/selection?${params.toString()}`);
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to load filtered review selection.");
        }
        reviewSelection.clear();
        (data.review_ids || []).forEach((id) => reviewSelection.add(Number(id)));
        syncCheckboxesFromSelection();
        updateSelectionUi();
        showToast(`Selected ${data.count} review${data.count === 1 ? "" : "s"} from the current filter.`, "success");
    } catch (error) {
        showToast("Failed to select filtered reviews: " + error.message, "error");
    }
}

function clearReviewSelection() {
    reviewSelection.clear();
    syncCheckboxesFromSelection();
    updateSelectionUi();
}

function handleMasterSelection(checked) {
    if (checked) {
        toggleFilteredSelection(true);
        return;
    }
    clearReviewSelection();
}

function hideAutoReplyPreview() {
    const panel = document.getElementById("autoReplyPreviewPanel");
    if (panel) panel.classList.add("is-hidden");
    autoReplyPreviewState = null;
}

function renderPreviewList(containerId, items, formatter) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "";
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "text-muted";
        empty.textContent = "None";
        container.appendChild(empty);
        return;
    }
    items.slice(0, 8).forEach((item) => {
        const row = document.createElement("div");
        row.className = "preview-item";
        row.textContent = formatter(item);
        container.appendChild(row);
    });
    if (items.length > 8) {
        const more = document.createElement("p");
        more.className = "text-muted";
        more.textContent = `+ ${items.length - 8} more`;
        container.appendChild(more);
    }
}

async function previewBulkAutoReplyUI() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        showToast("Select at least one review first.", "error");
        return;
    }
    try {
        const resp = await fetch("/api/reviews/bulk/auto-reply-preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ review_ids: reviewIds }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to preview auto reply.");
        }
        autoReplyPreviewState = data;
        const panel = document.getElementById("autoReplyPreviewPanel");
        const title = document.getElementById("autoReplyPreviewTitle");
        const eligibleCount = document.getElementById("autoReplyEligibleCount");
        const blockedCount = document.getElementById("autoReplyBlockedCount");
        const confirmButton = document.getElementById("confirmAutoReplyButton");
        if (title) {
            title.textContent = `${data.eligible_count} eligible, ${data.blocked_count} blocked`;
        }
        if (eligibleCount) eligibleCount.textContent = String(data.eligible_count);
        if (blockedCount) blockedCount.textContent = String(data.blocked_count);
        if (confirmButton) confirmButton.disabled = data.eligible_count === 0;
        renderPreviewList(
            "autoReplyEligibleList",
            data.eligible_reviews || [],
            (item) => `${item.store || "Unknown store"} · ${item.reviewer_name || "Anonymous"} · ${item.rating}/5`,
        );
        renderPreviewList(
            "autoReplyBlockedList",
            data.blocked_reviews || [],
            (item) => `${item.store || "Unknown store"} · ${item.reviewer_name || "Anonymous"} · ${item.reason}`,
        );
        if (panel) panel.classList.remove("is-hidden");
    } catch (error) {
        showToast("Failed to preview auto reply: " + error.message, "error");
    }
}

async function bulkAutoReplyUI() {
    if (!autoReplyPreviewState || !autoReplyPreviewState.eligible_count) {
        showToast("No eligible reviews are ready for auto reply.", "error");
        return;
    }
    try {
        const resp = await fetch("/api/reviews/bulk/auto-reply-ui", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ review_ids: selectedReviewIds() }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to start UI auto reply.");
        }
        showToast(
            `Auto Reply started for ${data.queued_count} review${data.queued_count === 1 ? "" : "s"}. Browser posting will run sequentially.`,
            "success",
        );
        hideAutoReplyPreview();
        clearReviewSelection();
        location.reload();
    } catch (error) {
        showToast("Failed to start UI auto reply: " + error.message, "error");
    }
}

async function bulkRegenerate() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        showToast("Select at least one review first.", "error");
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
        showToast(`Regenerated ${data.updated_reviews} review suggestion(s).`, "success");
        location.reload();
    }
}

function setupRatingFilterControls() {
    const allToggle = document.getElementById("rating-all");
    const starCheckboxes = Array.from(document.querySelectorAll(".rating-filter-checkbox"));
    if (!allToggle || !starCheckboxes.length) {
        return;
    }

    const syncAllToggle = () => {
        const checkedCount = starCheckboxes.filter((input) => input.checked).length;
        allToggle.checked = checkedCount === 0 || checkedCount === starCheckboxes.length;
    };

    allToggle.addEventListener("change", () => {
        starCheckboxes.forEach((input) => {
            input.checked = allToggle.checked;
        });
    });

    starCheckboxes.forEach((input) => {
        input.addEventListener("change", () => {
            const checkedCount = starCheckboxes.filter((node) => node.checked).length;
            if (checkedCount === 0) {
                allToggle.checked = true;
                starCheckboxes.forEach((node) => {
                    node.checked = true;
                });
                return;
            }
            syncAllToggle();
        });
    });

    const filterForm = document.getElementById("reviewFilterForm");
    if (filterForm) {
        filterForm.addEventListener("submit", () => {
            if (allToggle.checked) {
                starCheckboxes.forEach((input) => {
                    input.checked = false;
                });
            }
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    updateSelectionUi();
    setupRatingFilterControls();
});

async function bulkMarkHandled() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        showToast("Select at least one review first.", "error");
        return;
    }
    const resp = await fetch("/api/reviews/bulk/mark-handled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_ids: reviewIds, handled_by: "operator" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
        showToast(`Marked ${data.updated_reviews} review(s) as handled.`, "success");
        location.reload();
    }
}

function bulkExport() {
    const reviewIds = selectedReviewIds();
    if (!reviewIds.length) {
        showToast("Select at least one review first.", "error");
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
        showToast("Review marked as handled.", "success");
        location.reload();
    }
}

async function evaluateAutoReply(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/evaluate-auto-reply`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to evaluate auto reply.");
        }
        showToast(`Decision updated: ${data.decision.workflow_status.replaceAll("_", " ")}.`, "success");
        location.reload();
    } catch (error) {
        showToast("Failed to evaluate auto reply: " + error.message, "error");
    }
}

async function markReviewEscalated(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/mark-escalated`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to escalate review.");
        }
        showToast(`Review marked as ${data.workflow_status.replaceAll("_", " ")}.`, "success");
        location.reload();
    } catch (error) {
        showToast("Failed to mark review escalated: " + error.message, "error");
    }
}

async function markReviewManual(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/mark-manual`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to mark review manual.");
        }
        showToast(`Review marked as ${data.workflow_status.replaceAll("_", " ")}.`, "success");
        location.reload();
    } catch (error) {
        showToast("Failed to mark review manual: " + error.message, "error");
    }
}

async function autoReplyUI(reviewId) {
    try {
        const resp = await fetch(`/api/reviews/${reviewId}/auto-reply-ui`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to start UI posting.");
        }
        showToast("Auto Reply started. Waiting for job queue...", "success");
        window.setTimeout(() => {
            showToast("Opening browser to post the reply...", "info");
        }, 1200);
        location.reload();
    } catch (error) {
        showToast("Failed to start UI posting: " + error.message, "error");
    }
}

async function previewBulkAutoReply() {
    return previewBulkAutoReplyUI();
}

async function startBulkAutoReply() {
    return bulkAutoReplyUI();
}

async function retryAutoPost(reviewId) {
    return autoReplyUI(reviewId);
}

function parseSettingsForm(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    const payload = {};
    const checkboxFields = [
        "auto_reply_enabled",
        "auto_post_phase_enabled",
        "auto_reply_google_enabled",
        "auto_reply_yelp_enabled",
    ];
    checkboxFields.forEach((name) => {
        const input = form.querySelector(`[name="${name}"]`);
        if (input) {
            payload[name] = Boolean(input.checked);
        }
    });

    if (data.auto_reply_min_rating !== undefined) {
        payload.auto_reply_min_rating = data.auto_reply_min_rating ? Number(data.auto_reply_min_rating) : null;
    }
    if (data.auto_reply_daily_limit !== undefined) {
        payload.auto_reply_daily_limit = data.auto_reply_daily_limit ? Number(data.auto_reply_daily_limit) : null;
    }
    if (data.auto_reply_quiet_hours_start !== undefined) {
        payload.auto_reply_quiet_hours_start = data.auto_reply_quiet_hours_start || "";
    }
    if (data.auto_reply_quiet_hours_end !== undefined) {
        payload.auto_reply_quiet_hours_end = data.auto_reply_quiet_hours_end || "";
    }
    if (data.auto_reply_confidence_threshold !== undefined) {
        payload.auto_reply_confidence_threshold = data.auto_reply_confidence_threshold ? Number(data.auto_reply_confidence_threshold) : null;
    }
    if (data.auto_reply_blocked_keywords !== undefined) {
        payload.auto_reply_blocked_keywords = (data.auto_reply_blocked_keywords || "")
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    }
    if (data.auto_reply_escalation_emails !== undefined) {
        payload.auto_reply_escalation_emails = (data.auto_reply_escalation_emails || "")
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    }
    if (data.brand_tone_mode !== undefined) {
        payload.brand_tone_mode = data.brand_tone_mode || null;
    }
    return payload;
}

async function saveGlobalAutoReplyConfig(event) {
    event.preventDefault();
    try {
        const payload = parseSettingsForm(event.target);
        const resp = await fetch("/api/admin/auto-reply-config", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to save global auto-reply config.");
        }
        showToast("Global auto-reply policy saved.", "success");
        location.reload();
    } catch (error) {
        showToast("Failed to save global auto-reply config: " + error.message, "error");
    }
}

async function saveLocationAutoReplyConfig(event, locationId) {
    event.preventDefault();
    try {
        const payload = parseSettingsForm(event.target);
        const resp = await fetch(`/api/locations/${locationId}/auto-reply-config`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to save location auto-reply config.");
        }
        showToast("Location auto-reply policy saved.", "success");
        location.reload();
    } catch (error) {
        showToast("Failed to save location auto-reply config: " + error.message, "error");
    }
}

function runPresetCommand(command) {
    const input = document.getElementById("workspaceCommandInput");
    if (input) {
        input.value = command;
    }
    applyWorkspaceCommand(command);
}

function runCommandBar(event) {
    event.preventDefault();
    const input = document.getElementById("workspaceCommandInput");
    if (!input) return;
    applyWorkspaceCommand(input.value);
}

function applyWorkspaceCommand(rawCommand) {
    const command = (rawCommand || "").trim().toLowerCase();
    if (!command) {
        showToast("Enter a command first.", "error");
        return;
    }

    if (command.includes("1-star") || command.includes("1 star")) {
        const preset = command.includes("7") ? "7d" : command.includes("30") ? "30d" : "1d";
        window.location.href = `/reviews?ratings=1&date_preset=${preset}`;
        return;
    }
    if (command.includes("safe for auto reply") || command.includes("auto reply") || command.includes("auto-reply")) {
        window.location.href = "/auto-reply";
        return;
    }
    if (command.includes("gm report") || command.includes("report")) {
        window.location.href = "/reports";
        return;
    }
    if (command.includes("auth issue") || command.includes("blocked source") || command.includes("login expiry")) {
        window.location.href = "/locations";
        return;
    }
    if (command.includes("3 star") || command.includes("negative")) {
        window.location.href = "/audit";
        return;
    }

    showToast("START does not recognize that command yet. Try queue, auto reply, audit, or report commands.", "info");
}

async function sendDailyNegativeReport() {
    try {
        const resp = await fetch("/api/auto-reply/reports/daily-negative/send", { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || "Failed to send GM report.");
        }
        showToast(`GM report ${data.status}. ${data.review_count} review(s) included.`, data.status === "sent" ? "success" : "error");
    } catch (error) {
        showToast("Failed to send GM report: " + error.message, "error");
    }
}
