// ==UserScript==
// @name         Auto Upvote - Paint a Street
// @namespace    http://tampermonkey.net/
// @version      1.4
// @description  Automatically clicks the upvote button and waits for votes to reset when depleted
// @match        *://paintastreet.com/*
// @match        *://*.paintastreet.com/*
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    const TARGET_TILE_URL = 'https://paintastreet.com/#tile-019d589b-0d7b-720e-9a3c-1c8ecbc90a09';

    let lastLogMessage = '';
    let wasOutOfVotes = false;

    function log(message) {
        if (message !== lastLogMessage) {
            console.log(message);
            lastLogMessage = message;
        }
    }

    function getVotesRemaining() {
        const remainingEl = document.querySelector('.tile-vote-panel.is-visible .vote-remaining');
        if (!remainingEl) return null;

        let directText = '';
        for (const node of remainingEl.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) {
                directText += node.textContent;
            }
        }

        const match = directText.match(/(\d+)\s*votes?\s*remaining/i);
        if (match) return parseInt(match[1], 10);
        return null;
    }

    function isOutOfVotes() {
        return getVotesRemaining() === 0;
    }

    function getResetSeconds() {
        const countdownEl = document.querySelector('.tile-vote-panel.is-visible .countdown-numerals');
        if (!countdownEl) return null;

        const text = countdownEl.textContent.trim();
        const parts = text.split(':').map(Number);

        if (parts.length === 2) return parts[0] * 60 + parts[1];
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        return null;
    }

    function isBotCheckVisible() {
        const dialog = document.querySelector('section.submit-dialog.submit-dialog--auth');
        return !!dialog;
    }

    function tick() {
        if (isBotCheckVisible()) {
            log("[Auto Upvote Polite] Bot check dialog detected. Pausing...");
            return;
        }

        const panel = document.querySelector('.tile-vote-panel.is-visible');
        if (!panel) {
            log("[Auto Upvote Polite] No visible vote panel found. Navigating to target tile...");
            window.location.href = TARGET_TILE_URL;
            return;
        }

        if (isOutOfVotes()) {
            wasOutOfVotes = true;
            const seconds = getResetSeconds();
            if (seconds !== null && seconds <= 0) {
                console.log("[Auto Upvote Polite] Reset timer reached 0. Refreshing page...");
                window.location.reload();
                return;
            }
            log("[Auto Upvote Polite] 0 votes remaining. Waiting for reset...");
            return;
        }

        if (wasOutOfVotes) {
            console.log("[Auto Upvote Polite] Votes have reset. Refreshing page...");
            window.location.reload();
            return;
        }

        const buttons = panel.querySelectorAll('button.vote-button');
        let upvoteButton = null;

        for (const btn of buttons) {
            if (!btn.classList.contains('vote-button--negative')) {
                upvoteButton = btn;
                break;
            }
        }

        if (upvoteButton) {
            if (upvoteButton.disabled) {
                log("[Auto Upvote Polite] Upvote button is disabled. Waiting...");
                return;
            }
            lastLogMessage = '';
            console.log("[Auto Upvote Polite] Clicking upvote.");
            upvoteButton.click();
        } else {
            log("[Auto Upvote Polite] Upvote button not found in panel.");
        }
    }

    console.log("[Auto Upvote Polite] Script loaded. Starting loop...");
    setInterval(tick, 500);
})();
