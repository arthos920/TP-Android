JS_ACTIVATE_LOGGING = """
return (function() {
    if (typeof window.webchatSDK === 'undefined') {
        return false;
    }

    if (!window.webchatSDK.STWLogManager) {
        return false;
    }

    if (typeof window.webchatSDK.STWLogManager.setActive !== 'function') {
        return false;
    }

    window.webchatSDK.STWLogManager.setActive(true);
    return true;
})();
"""