/**
 * RAPP Store Configuration
 *
 * Default configuration values. For custom settings, create config.local.js
 * (copy from config.local.example.js) - it will be loaded first and override these defaults.
 */

// Merge local config with defaults
window.RAPP_CONFIG = Object.assign({
    // RAPPzoo live tick data (public, no auth required)
    RAPPZOO_TICK: 'https://raw.githubusercontent.com/kody-w/CommunityRAPP/main/rappzoo/world/current_tick.json',

    // Store manifest URL (null = use default RAPP_Store manifest)
    MANIFEST_URL: null,

    // RAPP API endpoint - set via Settings modal or config.local.js
    RAPP_API: null,

    // API key - set via Settings modal or config.local.js
    RAPP_API_KEY: null
}, window.RAPP_LOCAL_CONFIG || {});
