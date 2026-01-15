    html_block = f"""
    <div style="border:2px solid #d9534f; padding:5px; margin:5px 0;">
        <h3>
            {title} |
            <span style="color:#007bff;">Test: {test_name}</span><br>
            <span style="color:#d9534f; font-weight:bold;">
                Keyword: {failed_kw}
            </span>
        </h3>
        <a href="{rel_path}">
            <img src="{rel_path}" style="max-width:300px;">
        </a>
    </div>
    ""