
try:
    forced = driver.execute_script("""
        const btn = arguments[0];

        // si pas disabled, on ne force pas
        if (!btn.disabled && btn.getAttribute('aria-disabled') !== 'true') {
            return false;
        }

        const form = btn.closest('form');
        if (!form) return false;

        // déclencher validation
        form.querySelectorAll('input, textarea, select').forEach(el => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        });

        // enlever disabled
        btn.disabled = false;
        btn.removeAttribute('disabled');
        btn.setAttribute('aria-disabled', 'false');

        // submit direct
        form.submit();
        return true;
    """, component)

    if forced:
        shot(f"click_component_attempt_{attempt}_FORCED_FORM_SUBMIT")
        return

except Exception:
    shot(f"click_component_attempt_{attempt}_FORCED_SUBMIT_FAILED")