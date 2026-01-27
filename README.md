import time

def start_logging(self, log_file_path: str, log_url: str = None):
    """
    Start client trace logging to file.

    :param log_file_path: file name and path to write logs to
    :param log_url: for logging from websocket URL provided by appium server. Not in use for Agnet Dispatcher.
    """
    self.log_file_path = log_file_path

    # --- Inject JS to collect console logs safely ---
    try:
        self.driver.execute_script(r"""
            (function() {
                if (window.__loggingInitialized) return;
                window.__loggingInitialized = true;

                window.__browser_logs = window.__browser_logs || [];
                var originalConsole = {};
                var logLevels = ['log', 'info', 'warn', 'error', 'debug'];

                logLevels.forEach(function(level) {
                    if (!console[level]) return;
                    originalConsole[level] = console[level];
                    console[level] = function() {
                        try {
                            var message = Array.from(arguments).join(' ');
                            var timestamp = new Date().toISOString();
                            window.__browser_logs.push({
                                level: String(level).toUpperCase(),
                                message: message,
                                timestamp: timestamp
                            });
                        } catch (e) {}
                        try {
                            originalConsole[level].apply(console, arguments);
                        } catch (e) {}
                    };
                });
            })();
        """)
    except Exception:
        # On ne bloque pas les tests si l'injection échoue
        pass

    # --- Best-effort: enable webchatSDK logging if present (CI-safe) ---
    try:
        enabled = self.driver.execute_script(r"""
            try {
                if (window.webchatSDK &&
                    webchatSDK.STWLogManager &&
                    typeof webchatSDK.STWLogManager.setActive === 'function') {
                    webchatSDK.STWLogManager.setActive(true);
                    return true;
                }
                return false;
            } catch (e) {
                return false;
            }
        """)
    except Exception:
        enabled = False

    # Petit log côté Python (facultatif)
    try:
        print(f"webchatSDK enabled: {enabled}")
    except Exception:
        pass