failed_kw = BuiltIn().get_variable_value("${FAILED_KEYWORD}", "")
failed_msg = BuiltIn().get_variable_value("${FAILED_MESSAGE}", "")

html_block = f"""
<div style="
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    border:1px solid #ececec;
    border-radius:10px;
    background:#ffffff;
    padding:12px;
    margin:10px 0;
    max-width:820px;
    box-shadow:0 6px 18px rgba(0,0,0,0.08);
">

  <!-- Header -->
  <div style="
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      margin-bottom:10px;
  ">
    <div style="display:flex; align-items:center; gap:8px;">
      <span style="
          background:#d9534f;
          color:#fff;
          font-weight:800;
          font-size:12px;
          padding:4px 10px;
          border-radius:999px;
          letter-spacing:0.5px;
      ">FAIL</span>

      <span style="
          color:#111;
          font-weight:700;
          font-size:14px;
      ">{title}</span>
    </div>

    <span style="
        background:#f5f5f5;
        color:#555;
        font-size:12px;
        padding:4px 10px;
        border-radius:999px;
        border:1px solid #e9e9e9;
    ">
      📸 Screenshot
    </span>
  </div>

  <!-- Body -->
  <div style="display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap;">

    <!-- Left: QA Info panel -->
    <div style="
        flex: 1 1 360px;
        min-width:320px;
    ">

      <!-- Test badge -->
      <div style="margin-bottom:8px;">
        <div style="
            display:inline-block;
            background:#eef6ff;
            border:1px solid #d7ebff;
            color:#0b5ed7;
            font-weight:700;
            font-size:12px;
            padding:6px 10px;
            border-radius:8px;
        ">
          🧪 Test
        </div>

        <div style="
            margin-top:6px;
            color:#1f2937;
            font-size:13px;
            font-weight:700;
            line-height:1.25;
        ">
          {test_name}
        </div>
      </div>

      <!-- Optional keyword -->
      {f'''
      <div style="margin-top:10px;">
        <div style="
            display:inline-block;
            background:#fff7ed;
            border:1px solid #ffe1bf;
            color:#9a3412;
            font-weight:800;
            font-size:12px;
            padding:6px 10px;
            border-radius:8px;
        ">
          ⚙️ Keyword
        </div>
        <div style="
            margin-top:6px;
            color:#374151;
            font-size:12.5px;
            font-weight:700;
        ">
          {failed_kw}
        </div>
      </div>
      ''' if failed_kw else ''}

      <!-- Optional error message -->
      {f'''
      <div style="
          margin-top:10px;
          border:1px solid #f3c7c6;
          background:#fff5f5;
          border-radius:10px;
          padding:10px;
      ">
        <div style="
            display:flex;
            align-items:center;
            gap:8px;
            margin-bottom:6px;
        ">
          <span style="
              width:10px; height:10px; border-radius:50%;
              background:#d9534f; display:inline-block;
          "></span>
          <span style="font-weight:900; color:#b02a37; font-size:12px;">
            Failure details
          </span>
        </div>
        <div style="
            color:#7a1f2b;
            font-size:12px;
            line-height:1.35;
            white-space:pre-wrap;
            word-break:break-word;
        ">{failed_msg}</div>
      </div>
      ''' if failed_msg else ''}

      <!-- Footer mini -->
      <div style="
          margin-top:10px;
          display:flex;
          gap:8px;
          flex-wrap:wrap;
      ">
        <span style="
            background:#f6f6f6;
            border:1px solid #ededed;
            color:#666;
            font-size:11px;
            padding:4px 8px;
            border-radius:999px;
        ">Robot Log</span>

        <span style="
            background:#f6f6f6;
            border:1px solid #ededed;
            color:#666;
            font-size:11px;
            padding:4px 8px;
            border-radius:999px;
        ">Web</span>
      </div>
    </div>

    <!-- Right: Screenshot -->
    <div style="
        flex: 0 0 300px;
        min-width:300px;
        text-align:center;
    ">
      <a href="{rel_path}" style="text-decoration:none;">
        <img src="{rel_path}" style="
            width:300px;
            max-width:100%;
            border-radius:10px;
            border:1px solid #e6e6e6;
            box-shadow:0 10px 25px rgba(0,0,0,0.12);
            transition:transform 0.15s ease, box-shadow 0.15s ease;
        "
        onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 14px 34px rgba(0,0,0,0.18)';"
        onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 10px 25px rgba(0,0,0,0.12)';"
        >
      </a>

      <div style="margin-top:8px;">
        <a href="{rel_path}" style="
            display:inline-block;
            background:#111827;
            color:#fff;
            font-weight:800;
            font-size:12px;
            padding:6px 10px;
            border-radius:999px;
            text-decoration:none;
        ">🔍 Open full screenshot</a>
      </div>
    </div>

  </div>
</div>
"""