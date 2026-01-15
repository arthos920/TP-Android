html_block = f"""
<div style="
    border:1px solid #e0e0e0;
    border-left:5px solid #d9534f;
    padding:10px;
    margin:8px 0;
    max-width:520px;
    background:#fafafa;
    border-radius:6px;
    box-shadow:0 2px 6px rgba(0,0,0,0.08);
    font-family:Arial, sans-serif;
">

    <!-- Titre -->
    <h3 style="
        font-size:14px;
        margin:0 0 6px 0;
        text-align:left;
        color:#333;
    ">
        <span style="
            background:#d9534f;
            color:white;
            padding:2px 6px;
            border-radius:4px;
            font-size:12px;
            font-weight:bold;
            margin-right:6px;
        ">
            ERROR
        </span>
        <span style="color:#d9534f; font-weight:bold;">
            {title}
        </span>
    </h3>

    <!-- Test -->
    <div style="text-align:left; margin-bottom:6px;">
        <span style="
            display:inline-block;
            background:#e9f2ff;
            color:#007bff;
            padding:3px 8px;
            border-radius:12px;
            font-size:12px;
            font-weight:bold;
        ">
            🧪 Test : {test_name}
        </span>
    </div>

    <!-- Image centrée -->
    <div style="text-align:center;">
        <a href="{rel_path}" style="text-decoration:none;">
            <img src="{rel_path}" style="
                max-width:260px;
                border:1px solid #ccc;
                border-radius:4px;
                box-shadow:0 1px 4px rgba(0,0,0,0.1);
            ">
        </a>
    </div>

</div>
"""